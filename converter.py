"""MIDI listening and OSC routing logic."""

from typing import Any, Dict, List, Tuple, Union
import mido
from pythonosc import udp_client

# Use a set for O(1) lookup time instead of tuple evaluation inside the loop
SUPPORTED_TYPES = {"note_on", "note_off", "control_change", "program_change", "sysex"}


def run_converter(
    port_name: str,
    osc_ip: str,
    osc_port: int,
    mappings: Dict[Tuple[str, Any, Any], str],
) -> None:
    """Main loop listening on MIDI port and dispatching OSC messages."""

    # 0. Resolve matching MIDI port if an exact name match is not provided
    available_ports = mido.get_input_names()  # type: ignore[attr-defined]
    target_port = port_name

    if port_name not in available_ports:
        # Perform a case-insensitive partial match search
        matched = [p for p in available_ports if port_name.lower() in p.lower()]
        if matched:
            target_port = matched[0]
        else:
            raise RuntimeError(
                f"MIDI Port '{port_name}' not found. Available ports: {available_ports}"
            )

    client = udp_client.SimpleUDPClient(osc_ip, osc_port)

    with mido.open_input(target_port) as inport:  # pylint: disable=no-member
        for msg in inport:
            if msg.type not in SUPPORTED_TYPES:
                continue

            # 1. Parse incoming MIDI message into uniform internal format
            msg_type = msg.type
            if msg_type in ("note_on", "note_off"):
                channel = msg.channel
                num = msg.note
                # Treat velocity 0 as note_off logically if needed, but lookup key uses note_on
                val = 0 if msg_type == "note_off" else msg.velocity
                lookup_type = "note_on"
                midi_sig = f"note {channel} {num}"
                default_addr = (
                    f"/midi/channel/{channel}/note_on"
                    if msg_type == "note_on"
                    else f"/midi/channel/{channel}/note_off"
                )
                default_val: Union[int, List[int]] = [num, val]

            elif msg_type == "control_change":
                channel = msg.channel
                num = msg.control
                val = msg.value
                lookup_type = "control_change"
                midi_sig = f"cc {channel} {num}"
                default_addr = f"/midi/channel/{channel}/cc/{num}"
                default_val = val

            elif msg_type == "program_change":
                channel = msg.channel
                num = msg.program
                val = msg.program
                lookup_type = "program_change"
                midi_sig = f"pc {channel} {num}"
                default_addr = f"/midi/channel/{channel}/program_change"
                default_val = val

            elif msg_type == "sysex":
                channel = None
                num = None
                val = list(msg.data)
                lookup_type = "sysex"
                midi_sig = "sysex"
                default_addr = "/midi/sysex"
                default_val = val

            key = (lookup_type, channel, num)

            # 2. Dispatch mapped or default OSC message
            if key in mappings:
                osc_addr = mappings[key]
                send_val = val
                val_str = (
                    " ".join(map(str, send_val))
                    if isinstance(send_val, (list, tuple))
                    else str(send_val)
                )

                client.send_message(osc_addr, send_val)
                print(
                    f"MIDI IN: {midi_sig:<12} ➔ MAPPED  -> {osc_addr} [{val_str}]"
                )
            else:
                osc_addr = default_addr
                send_val = default_val
                val_str = (
                    " ".join(map(str, send_val))
                    if isinstance(send_val, (list, tuple))
                    else str(send_val)
                )

                client.send_message(osc_addr, send_val)
                print(
                    f"MIDI IN: {midi_sig:<12} ➔ DEFAULT -> {osc_addr} [{val_str}]"
                )
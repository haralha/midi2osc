"""MIDI listening and OSC routing logic."""

import threading
from typing import Any, Dict, List, Optional, Tuple, Union
import mido
from pythonosc import udp_client

SUPPORTED_TYPES = {"note_on", "note_off", "control_change", "program_change", "sysex"}


class MidiPortError(RuntimeError):
    """Raised after MIDI port diagnostics have already been printed."""


def run_converter(
    port_name: str,
    osc_ip: str,
    osc_port: int,
    mappings: Dict[Tuple[str, Any, Any], str],
    stop_event: Optional[threading.Event] = None,
    convert_unmapped: bool = True,
) -> None:
    """Main loop listening on MIDI port and dispatching OSC messages."""

    available_ports = mido.get_input_names()  # type: ignore[attr-defined]

    if not available_ports:
        raise RuntimeError("No MIDI input devices found on the system.")

    clean_port_name = port_name.strip() if port_name else ""

    def _print_available_ports() -> None:
        print("Available MIDI input ports:")
        for i, name in enumerate(available_ports):
            print(f"  [{i}] {name}")

    if not clean_port_name:
        _print_available_ports()
        print("✖ Error: No MIDI port specified in configuration.")
        raise MidiPortError("No MIDI port specified in configuration.")

    target_port = None

    if clean_port_name in available_ports:
        target_port = clean_port_name
    else:
        matched = [p for p in available_ports if clean_port_name.lower() in p.lower()]
        if matched:
            target_port = matched[0]
            print(f"✔ Connected to MIDI Port: '{target_port}' (matched from '{clean_port_name}')")
        else:
            _print_available_ports()
            print(f"✖ Error: MIDI Port '{clean_port_name}' not found.")
            raise MidiPortError(f"MIDI Port '{clean_port_name}' not found.")

    client = udp_client.SimpleUDPClient(osc_ip, osc_port)

    with mido.open_input(target_port) as inport:  # pylint: disable=no-member
        # Non-blocking loop checking for stop_event
        while stop_event is None or not stop_event.is_set():
            # iter_pending yields all available incoming messages without blocking forever
            for msg in inport.iter_pending():
                if msg.type not in SUPPORTED_TYPES:
                    continue

                msg_type = msg.type
                if msg_type in ("note_on", "note_off"):
                    channel = msg.channel
                    num = msg.note
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
                    send_val = default_val
                    val_str = (
                        " ".join(map(str, send_val))
                        if isinstance(send_val, (list, tuple))
                        else str(send_val)
                    )

                    if convert_unmapped:
                        client.send_message(default_addr, send_val)
                        print(
                            f"MIDI IN: {midi_sig:<12} ➔ DEFAULT -> {default_addr} [{val_str}]"
                        )
                    else:
                        print(
                            f"MIDI IN: {midi_sig:<12} ➔ UNMAPPED (LOGGED ONLY) [{val_str}]"
                        )
                        
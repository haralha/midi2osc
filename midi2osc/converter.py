"""MIDI listening and OSC routing logic."""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, NoReturn, Optional, Union

import mido
from pythonosc import udp_client

from midi2osc.config import AppConfig, MappingKey, OscMapping, parse_config
from midi2osc.expr import ExprError, evaluate_osc_value
from midi2osc.logging_utils import build_routed_tokens

logger = logging.getLogger("midi2osc")

SUPPORTED_TYPES = {"note_on", "note_off", "control_change", "program_change", "sysex"}

# How often to verify the MIDI device is still present while the callback is active.
PORT_CHECK_S = 1.0
RECONNECT_WAIT_S = 1.0


class MidiPortError(RuntimeError):
    """Raised when a MIDI port cannot be resolved or opened."""


class MidiPortConfigError(MidiPortError):
    """Configured MIDI port name is empty, unknown, or ambiguous."""


OscValue = Union[int, float, str, list[int]]


@dataclass(frozen=True)
class RoutedMessage:
    """Result of mapping a MIDI message to an OSC destination."""

    midi_sig: str
    osc_address: str
    value: OscValue
    mapped: bool
    send: bool

def resolve_midi_port(port_name: str, available_ports: Optional[list[str]] = None) -> str:
    """Resolve a configured MIDI port name to an available system port.

    Match order:
    1. Exact match
    2. Case-insensitive exact match
    3. Unique case-insensitive substring match
    """
    available = available_ports if available_ports is not None else list(
        mido.get_input_names()  # type: ignore[attr-defined]
    )

    if not available:
        raise MidiPortError("No MIDI input devices found on the system.")

    clean = (port_name or "").strip()
    if not clean:
        _raise_unknown_port(
            available,
            "No MIDI port specified in configuration. "
            "Set midi_port in your mapping config to one of the names listed above.",
        )

    if clean in available:
        return clean

    lower_map = {p.lower(): p for p in available}
    if clean.lower() in lower_map:
        resolved = lower_map[clean.lower()]
        logger.info("Connected to MIDI port '%s' (case-insensitive match)", resolved)
        return resolved

    matched = [p for p in available if clean.lower() in p.lower()]
    if len(matched) == 1:
        logger.info(
            "Connected to MIDI port '%s' (matched from '%s')", matched[0], clean
        )
        return matched[0]
    if len(matched) > 1:
        _raise_unknown_port(
            available,
            f"MIDI port '{clean}' is ambiguous; matches: {', '.join(matched)}. "
            "Update midi_port in your mapping config to the exact device name.",
        )

    _raise_unknown_port(
        available,
        f"MIDI port '{clean}' not found. "
        "Update midi_port in your mapping config to one of the names listed above.",
    )


def _log_available_ports(ports: list[str]) -> None:
    logger.info("Available MIDI input ports:")
    for i, name in enumerate(ports):
        logger.info("  [%s] %s", i, name)


def _raise_unknown_port(ports: list[str], message: str) -> NoReturn:
    """Log available ports once, then raise a non-retryable config error."""
    _log_available_ports(ports)
    raise MidiPortConfigError(message)


def route_midi_message(
    msg: Any,
    mappings: dict[MappingKey, OscMapping],
    convert_unmapped: bool = True,
) -> Optional[RoutedMessage]:
    """Map a mido-like message to an OSC route, or None if unsupported."""
    if getattr(msg, "type", None) not in SUPPORTED_TYPES:
        return None

    msg_type: str = msg.type

    # MIDI convention: note_on with velocity 0 is note_off
    if msg_type == "note_on" and getattr(msg, "velocity", 0) == 0:
        msg_type = "note_off"

    if msg_type in ("note_on", "note_off"):
        channel = msg.channel
        num = msg.note
        val = 0 if msg_type == "note_off" else msg.velocity
        # Mapped "note" / "note_on" entries cover both on and off
        lookup_type = "note_on"
        midi_sig = f"note {channel} {num}"
        default_addr = (
            f"/midi/channel/{channel}/note_on"
            if msg_type == "note_on"
            else f"/midi/channel/{channel}/note_off"
        )
        default_val: OscValue = [num, val]

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

    else:
        return None

    key: MappingKey = (lookup_type, channel, num)

    if key in mappings:
        mapping = mappings[key]
        out_value: OscValue = val
        send = True
        if mapping.value_expr is not None:
            if isinstance(val, list):
                logger.warning(
                    "Value expression ignored for %s (list payloads unsupported)",
                    midi_sig,
                )
                send = False
            else:
                try:
                    out_value = evaluate_osc_value(mapping.value_expr, int(val))
                except ExprError as exc:
                    logger.warning(
                        "Failed to evaluate %r for %s (v=%s): %s",
                        mapping.value_expr,
                        midi_sig,
                        val,
                        exc,
                    )
                    send = False
        return RoutedMessage(
            midi_sig=midi_sig,
            osc_address=mapping.address,
            value=out_value,
            mapped=True,
            send=send,
        )

    return RoutedMessage(
        midi_sig=midi_sig,
        osc_address=default_addr,
        value=default_val,
        mapped=False,
        send=convert_unmapped,
    )


def _log_routed(routed: RoutedMessage) -> None:
    """Log a routed MIDI event using the shared token layout."""
    message = "".join(text for _, text in build_routed_tokens(routed))
    logger.info(message, extra={"routed_msg": routed})


def _should_stop(stop_event: Optional[threading.Event]) -> bool:
    return stop_event is not None and stop_event.is_set()


def _wait_idle(stop_event: Optional[threading.Event], timeout: float) -> bool:
    """Wait for stop or timeout. Returns True if stop was requested."""
    if stop_event is None:
        time.sleep(timeout)
        return False
    return stop_event.wait(timeout)


def _dispatch_message(
    msg: Any,
    mappings: dict[MappingKey, OscMapping],
    convert_unmapped: bool,
    client: Any,
    osc_errors: list[int],
) -> None:
    routed = route_midi_message(msg, mappings, convert_unmapped)
    if routed is None:
        return

    if routed.send:
        try:
            client.send_message(routed.osc_address, routed.value)
        except OSError as exc:
            osc_errors[0] += 1
            if osc_errors[0] == 1 or osc_errors[0] % 50 == 0:
                logger.error(
                    "OSC send failed (%s errors): %s",
                    osc_errors[0],
                    exc,
                )

    _log_routed(routed)


def _open_mido_input(
    name: str,
    callback: Optional[Callable[[Any], None]] = None,
    *,
    virtual: bool = False,
) -> Any:
    return mido.open_input(name, callback=callback, virtual=virtual)


def _resolve_listen_port(port_name: str, *, virtual: bool, get_names: Callable[[], list[str]]) -> str:
    """Return the MIDI port name to open, creating a virtual port when requested."""
    clean = (port_name or "").strip()
    if virtual:
        if not clean:
            raise MidiPortConfigError(
                "No MIDI port specified in configuration. "
                "Set midi_port to the virtual port name to create "
                '(for example midi_port = "MIDI2OSC Bridge").'
            )
        # Windows cannot create virtual MIDI ports via mido/rtmidi.
        if sys.platform == "win32":
            raise MidiPortConfigError(
                "Virtual MIDI ports are not supported on Windows. "
                "Create a port with loopMIDI (or similar), set virtual = false, "
                f"and point midi_port at that port name (wanted: '{clean}')."
            )
        return clean

    return resolve_midi_port(port_name, available_ports=get_names())


def run_converter(
    port_name: str,
    osc_ip: str,
    osc_port: int,
    mappings: dict[MappingKey, OscMapping],
    stop_event: Optional[threading.Event] = None,
    convert_unmapped: bool = True,
    *,
    virtual: bool = False,
    reconnect: bool = True,
    client_factory: Optional[Callable[[str, int], Any]] = None,
    open_input: Optional[Callable[..., Any]] = None,
    list_inputs: Optional[Callable[[], list[str]]] = None,
) -> None:
    """Listen on a MIDI port and dispatch OSC messages.

    Incoming MIDI is handled via the backend callback (no poll/sleep loop).
    The converter thread blocks until ``stop_event`` is set, and periodically
    checks that the device is still present so dropped ports can reconnect.

    When ``virtual`` is True (macOS/Linux), a virtual MIDI input named
    ``port_name`` is created so other apps can send into this process.
    Windows rejects virtual mode with ``MidiPortConfigError``.

    When ``reconnect`` is True (default), dropped devices are retried until
    ``stop_event`` is set. A wrong or ambiguous port name is a config error
    (``MidiPortConfigError``) and is not retried. Raises ``MidiPortError`` if
    no devices are present and reconnect is disabled.
    """
    make_client = client_factory or (
        lambda ip, port: udp_client.SimpleUDPClient(ip, port)
    )
    open_port = open_input or _open_mido_input
    get_names = list_inputs or (
        lambda: list(mido.get_input_names())  # type: ignore[attr-defined]
    )

    client = make_client(osc_ip, osc_port)
    osc_errors = [0]

    while not _should_stop(stop_event):
        try:
            target_port = _resolve_listen_port(
                port_name, virtual=virtual, get_names=get_names
            )
        except MidiPortConfigError:
            # Typo / unknown name / unsupported virtual mode: do not retry.
            raise
        except MidiPortError as exc:
            if not reconnect:
                raise
            logger.error(
                "MIDI port unavailable (%s); retrying in %.1fs...",
                exc,
                RECONNECT_WAIT_S,
            )
            if _wait_idle(stop_event, RECONNECT_WAIT_S):
                return
            continue

        def on_midi(msg: Any) -> None:
            if _should_stop(stop_event):
                return
            _dispatch_message(msg, mappings, convert_unmapped, client, osc_errors)

        try:
            if virtual:
                logger.info("Creating virtual MIDI input: '%s'", target_port)
            with open_port(target_port, callback=on_midi, virtual=virtual):
                logger.info("Listening on MIDI: '%s'", target_port)
                while not _should_stop(stop_event):
                    if _wait_idle(stop_event, PORT_CHECK_S):
                        return
                    # Virtual ports are owned by this process; skip device presence checks.
                    if not virtual and target_port not in get_names():
                        raise RuntimeError(f"MIDI port '{target_port}' disconnected")

        except MidiPortError:
            raise
        except Exception as exc:
            if _should_stop(stop_event):
                return
            if not reconnect:
                raise
            logger.error(
                "MIDI connection lost (%s); reconnecting in %.1fs...",
                exc,
                RECONNECT_WAIT_S,
            )
            if _wait_idle(stop_event, RECONNECT_WAIT_S):
                return


def run_from_config(
    config: AppConfig,
    stop_event: Optional[threading.Event] = None,
    *,
    reconnect: bool = True,
) -> None:
    """Run the converter using a parsed AppConfig."""
    logger.info("Target OSC: %s:%s", config.ip, config.port)
    logger.info("Convert unmapped: %s", config.convert_unmapped)
    logger.info("Virtual MIDI port: %s", config.virtual)
    logger.info("Mappings loaded: %s", len(config.mappings))

    run_converter(
        config.midi_port,
        config.ip,
        config.port,
        config.mappings,
        stop_event=stop_event,
        convert_unmapped=config.convert_unmapped,
        virtual=config.virtual,
        reconnect=reconnect,
    )


def run_from_config_path(
    config_path: Path,
    stop_event: Optional[threading.Event] = None,
    *,
    reconnect: bool = True,
) -> AppConfig:
    """Parse config from disk and run the converter. Returns the config used."""
    config = parse_config(config_path)
    logger.info("Active config: %s", config_path.name)
    run_from_config(config, stop_event=stop_event, reconnect=reconnect)
    return config

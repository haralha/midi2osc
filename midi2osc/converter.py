"""MIDI listening and OSC routing logic."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Union

import mido
from pythonosc import udp_client

from midi2osc.config import AppConfig, MappingKey, parse_config

logger = logging.getLogger("midi2osc")

SUPPORTED_TYPES = {"note_on", "note_off", "control_change", "program_change", "sysex"}

# Idle poll interval — avoids busy-waiting while remaining responsive to stop_event.
IDLE_WAIT_S = 0.001
RECONNECT_WAIT_S = 1.0


class MidiPortError(RuntimeError):
    """Raised when a MIDI port cannot be resolved or opened."""


OscValue = Union[int, list[int]]


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
        _log_available_ports(available)
        raise MidiPortError("No MIDI port specified in configuration.")

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
        _log_available_ports(available)
        raise MidiPortError(
            f"MIDI port '{clean}' is ambiguous; matches: {', '.join(matched)}"
        )

    _log_available_ports(available)
    raise MidiPortError(f"MIDI port '{clean}' not found.")


def _log_available_ports(ports: list[str]) -> None:
    logger.info("Available MIDI input ports:")
    for i, name in enumerate(ports):
        logger.info("  [%s] %s", i, name)


def route_midi_message(
    msg: Any,
    mappings: dict[MappingKey, str],
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
        return RoutedMessage(
            midi_sig=midi_sig,
            osc_address=mappings[key],
            value=val,
            mapped=True,
            send=True,
        )

    return RoutedMessage(
        midi_sig=midi_sig,
        osc_address=default_addr,
        value=default_val,
        mapped=False,
        send=convert_unmapped,
    )


def _format_value(value: OscValue) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(map(str, value))
    return str(value)


def _log_routed(routed: RoutedMessage) -> None:
    val_str = _format_value(routed.value)
    if routed.mapped:
        logger.info(
            "MIDI IN: %-12s ➔ MAPPED  -> %s [%s]",
            routed.midi_sig,
            routed.osc_address,
            val_str,
        )
    elif routed.send:
        logger.info(
            "MIDI IN: %-12s ➔ DEFAULT -> %s [%s]",
            routed.midi_sig,
            routed.osc_address,
            val_str,
        )
    else:
        logger.info(
            "MIDI IN: %-12s ➔ UNMAPPED (LOGGED ONLY) [%s]",
            routed.midi_sig,
            val_str,
        )


def _should_stop(stop_event: Optional[threading.Event]) -> bool:
    return stop_event is not None and stop_event.is_set()


def _wait_idle(stop_event: Optional[threading.Event], timeout: float = IDLE_WAIT_S) -> bool:
    """Wait briefly for stop or timeout. Returns True if stop was requested."""
    if stop_event is None:
        time.sleep(timeout)
        return False
    return stop_event.wait(timeout)


def run_converter(
    port_name: str,
    osc_ip: str,
    osc_port: int,
    mappings: dict[MappingKey, str],
    stop_event: Optional[threading.Event] = None,
    convert_unmapped: bool = True,
    *,
    reconnect: bool = True,
    client_factory: Optional[Callable[[str, int], Any]] = None,
    open_input: Optional[Callable[[str], Any]] = None,
) -> None:
    """Listen on a MIDI port and dispatch OSC messages.

    When ``reconnect`` is True (default), dropped devices are retried until
    ``stop_event`` is set. Raises ``MidiPortError`` if the port cannot be
    resolved on the first attempt and reconnect is disabled.
    """
    make_client = client_factory or (
        lambda ip, port: udp_client.SimpleUDPClient(ip, port)
    )
    open_port = open_input or (lambda name: mido.open_input(name))

    client = make_client(osc_ip, osc_port)
    osc_errors = 0

    while not _should_stop(stop_event):
        try:
            target_port = resolve_midi_port(port_name)
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

        try:
            with open_port(target_port) as inport:
                logger.info("Listening on MIDI: '%s'", target_port)
                while not _should_stop(stop_event):
                    pending = list(inport.iter_pending())
                    if not pending:
                        if _wait_idle(stop_event):
                            return
                        continue

                    for msg in pending:
                        if _should_stop(stop_event):
                            return

                        routed = route_midi_message(msg, mappings, convert_unmapped)
                        if routed is None:
                            continue

                        if routed.send:
                            try:
                                client.send_message(routed.osc_address, routed.value)
                            except OSError as exc:
                                osc_errors += 1
                                if osc_errors == 1 or osc_errors % 50 == 0:
                                    logger.error(
                                        "OSC send failed (%s errors): %s",
                                        osc_errors,
                                        exc,
                                    )

                        _log_routed(routed)

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
    logger.info("Mappings loaded: %s", len(config.mappings))

    run_converter(
        config.midi_port,
        config.ip,
        config.port,
        config.mappings,
        stop_event=stop_event,
        convert_unmapped=config.convert_unmapped,
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

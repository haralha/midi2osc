"""MIDI port resolution and connection errors."""

from __future__ import annotations

import logging
import sys
from typing import Any, Callable, NoReturn, Optional

import mido

from midi2osc.logging_utils import log_status

logger = logging.getLogger("midi2osc")


class MidiPortError(RuntimeError):
    """Raised when a MIDI port cannot be resolved or opened."""


class MidiPortConfigError(MidiPortError):
    """Configured MIDI port name is empty, unknown, or ambiguous."""


class MidiPortDisconnected(RuntimeError):
    """Raised when an open MIDI port disappears."""


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
        log_status("Connected to MIDI port '%s' (case-insensitive match)", resolved)
        return resolved

    matched = [p for p in available if clean.lower() in p.lower()]
    if len(matched) == 1:
        log_status(
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
    log_status("Available MIDI input ports:")
    for i, name in enumerate(ports):
        log_status("  [%s] %s", i, name)


def _raise_unknown_port(ports: list[str], message: str) -> NoReturn:
    """Log available ports once, then raise a non-retryable config error."""
    _log_available_ports(ports)
    raise MidiPortConfigError(message)


def open_mido_input(
    name: str,
    callback: Optional[Callable[[Any], None]] = None,
    *,
    virtual: bool = False,
) -> Any:
    """Open a MIDI input, optionally creating a virtual port named ``name``.

    For virtual ports ``client_name`` is set too, so hosts that display the
    ALSA/CoreMIDI client rather than the port show ``name`` instead of
    rtmidi's default ("RtMidiIn Client"). mido forces virtual mode whenever
    ``client_name`` is passed, so it is only sent for virtual ports.
    """
    if virtual:
        return mido.open_input(
            name, callback=callback, virtual=True, client_name=name
        )
    return mido.open_input(name, callback=callback)


def resolve_listen_port(
    port_name: str, *, virtual: bool, get_names: Callable[[], list[str]]
) -> str:
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

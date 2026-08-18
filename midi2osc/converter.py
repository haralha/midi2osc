"""MIDI listening and OSC routing logic."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional, Union

import mido
from pythonosc import udp_client

from midi2osc.config import (
    ALL_CHANNELS,
    AppConfig,
    MappingKey,
    OscMapping,
    format_channels,
    parse_config,
)
from midi2osc.expr import ExprError, eval_value_expr
from midi2osc.logging_utils import build_routed_tokens, log_status
from midi2osc.ports import (
    MidiPortConfigError,
    MidiPortDisconnected,
    MidiPortError,
    open_mido_input,
    resolve_listen_port,
    resolve_midi_port,
)

__all__ = [
    "MidiPortConfigError",
    "MidiPortDisconnected",
    "MidiPortError",
    "RoutedMessage",
    "resolve_midi_port",
    "route_midi_message",
    "run_converter",
    "run_from_config",
    "run_from_config_path",
]

logger = logging.getLogger("midi2osc")

SUPPORTED_TYPES = {"note_on", "note_off", "control_change", "program_change", "sysex"}

# How often to verify the MIDI device is still present while listening.
PORT_CHECK_S = 1.0
RECONNECT_WAIT_S = 1.0
# How long the worker waits for the next queued MIDI message before checking stop/port.
QUEUE_POLL_S = 0.05

OscValue = Union[int, float, str, list[int]]


@dataclass
class _OscSendStats:
    errors: int = 0


@dataclass(frozen=True)
class _DecodedMidi:
    lookup_type: str
    channel: Optional[int]
    number: Optional[int]
    value: OscValue
    midi_sig: str
    default_addr: str
    default_val: OscValue


@dataclass(frozen=True)
class RoutedMessage:
    """Result of mapping a MIDI message to an OSC destination."""

    midi_sig: str
    osc_address: str
    value: OscValue
    mapped: bool
    send: bool
    muted: bool = False


def _decode_midi(msg: Any) -> Optional[_DecodedMidi]:
    """Normalize a mido-like message into lookup fields and fallback OSC values."""
    msg_type = getattr(msg, "type", None)
    if msg_type not in SUPPORTED_TYPES:
        return None

    # MIDI convention: note_on with velocity 0 is note_off
    if msg_type == "note_on" and getattr(msg, "velocity", 0) == 0:
        msg_type = "note_off"

    if msg_type in ("note_on", "note_off"):
        channel = msg.channel
        display_ch = channel + 1  # 1-16, same as config / DAWs
        number = msg.note
        velocity = 0 if msg_type == "note_off" else int(msg.velocity)
        default_addr = (
            f"/midi/channel/{display_ch}/note_on"
            if msg_type == "note_on"
            else f"/midi/channel/{display_ch}/note_off"
        )
        return _DecodedMidi(
            lookup_type="note_on",
            channel=channel,
            number=number,
            value=velocity,
            midi_sig=f"{msg_type} {display_ch} {number}",
            default_addr=default_addr,
            default_val=[number, velocity],
        )

    if msg_type == "control_change":
        channel = msg.channel
        display_ch = channel + 1
        number = msg.control
        value = msg.value
        return _DecodedMidi(
            lookup_type="control_change",
            channel=channel,
            number=number,
            value=value,
            midi_sig=f"cc {display_ch} {number}",
            default_addr=f"/midi/channel/{display_ch}/cc/{number}",
            default_val=value,
        )

    if msg_type == "program_change":
        channel = msg.channel
        display_ch = channel + 1
        number = msg.program
        return _DecodedMidi(
            lookup_type="program_change",
            channel=channel,
            number=number,
            value=number,
            midi_sig=f"pc {display_ch} {number}",
            default_addr=f"/midi/channel/{display_ch}/program_change",
            default_val=number,
        )

    if msg_type == "sysex":
        value = list(msg.data)
        return _DecodedMidi(
            lookup_type="sysex",
            channel=None,
            number=None,
            value=value,
            midi_sig="sysex",
            default_addr="/midi/sysex",
            default_val=value,
        )

    return None


def route_midi_message(
    msg: Any,
    mappings: dict[MappingKey, OscMapping],
    convert_unmapped: bool = True,
    listen_channels: frozenset[int] = ALL_CHANNELS,
) -> Optional[RoutedMessage]:
    """Map a mido-like message to an OSC route, or None if unsupported.

    Messages on a channel outside ``listen_channels`` (0-based) return None and
    are dropped. SysEx carries no channel and is always routed.
    """
    decoded = _decode_midi(msg)
    if decoded is None:
        return None

    if decoded.channel is not None and decoded.channel not in listen_channels:
        return None

    key = MappingKey(decoded.lookup_type, decoded.channel, decoded.number)
    mapping = mappings.get(key)
    if mapping is None:
        return RoutedMessage(
            midi_sig=decoded.midi_sig,
            osc_address=decoded.default_addr,
            value=decoded.default_val,
            mapped=False,
            send=convert_unmapped,
        )

    out_value: OscValue = decoded.value
    send = True
    if mapping.compiled_expr is not None:
        if isinstance(decoded.value, list):
            logger.warning(
                "Value expression ignored for %s (list payloads unsupported)",
                decoded.midi_sig,
            )
            send = False
        else:
            try:
                out_value = eval_value_expr(mapping.compiled_expr, int(decoded.value))
            except ExprError as exc:
                logger.warning(
                    "Failed to evaluate %r for %s (v=%s): %s",
                    mapping.value_expr,
                    decoded.midi_sig,
                    decoded.value,
                    exc,
                )
                send = False

    return RoutedMessage(
        midi_sig=decoded.midi_sig,
        osc_address=mapping.address,
        value=out_value,
        mapped=True,
        send=send,
    )


def _log_routed(routed: RoutedMessage) -> None:
    """Log a routed MIDI event using the shared token layout."""
    tokens = build_routed_tokens(routed)
    message = "".join(text for _, text in tokens)
    logger.info(message, extra={"routed_msg": routed, "routed_tokens": tokens})


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
    osc_stats: _OscSendStats,
    muted: bool = False,
    listen_channels: frozenset[int] = ALL_CHANNELS,
) -> None:
    routed = route_midi_message(msg, mappings, convert_unmapped, listen_channels)
    if routed is None:
        return

    if muted:
        _log_routed(replace(routed, muted=True))
        return

    if routed.send:
        try:
            client.send_message(routed.osc_address, routed.value)
        except OSError as exc:
            osc_stats.errors += 1
            if osc_stats.errors == 1 or osc_stats.errors % 50 == 0:
                logger.error(
                    "OSC send failed (%s errors): %s",
                    osc_stats.errors,
                    exc,
                )

    _log_routed(routed)


def _drain_queue(msg_queue: queue.SimpleQueue[Any]) -> None:
    while True:
        try:
            msg_queue.get_nowait()
        except queue.Empty:
            return


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
    listen_channels: frozenset[int] = ALL_CHANNELS,
    mute_event: Optional[threading.Event] = None,
    client_factory: Optional[Callable[[str, int], Any]] = None,
    open_input: Optional[Callable[..., Any]] = None,
    list_inputs: Optional[Callable[[], list[str]]] = None,
) -> None:
    """Listen on a MIDI port and dispatch OSC messages.

    Incoming MIDI is queued from the backend callback so the realtime thread
    stays thin. The converter thread routes, sends OSC, and logs.

    The converter thread blocks until ``stop_event`` is set, and periodically
    checks that the device is still present so dropped ports can reconnect.

    When ``virtual`` is True (macOS/Linux), a virtual MIDI input named
    ``port_name`` is created so other apps can send into this process.
    Windows rejects virtual mode with ``MidiPortConfigError``.

    ``listen_channels`` holds the 0-based MIDI channels to accept; messages on
    any other channel are dropped without logging. Defaults to all 16.

    While ``mute_event`` is set, messages are still routed and logged but no
    OSC packets are sent. The event is read per message, so it can be toggled
    from another thread without restarting the converter.

    When ``reconnect`` is True (default), dropped devices are retried until
    ``stop_event`` is set. A wrong or ambiguous port name is a config error
    (``MidiPortConfigError``) and is not retried. Raises ``MidiPortError`` if
    no devices are present and reconnect is disabled.
    """
    make_client = client_factory or (
        lambda ip, port: udp_client.SimpleUDPClient(ip, port)
    )
    open_port = open_input or open_mido_input
    get_names = list_inputs or (
        lambda: list(mido.get_input_names())  # type: ignore[attr-defined]
    )

    client = make_client(osc_ip, osc_port)
    osc_stats = _OscSendStats()

    while not _should_stop(stop_event):
        try:
            target_port = resolve_listen_port(
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

        msg_queue: queue.SimpleQueue[Any] = queue.SimpleQueue()

        def on_midi(msg: Any) -> None:
            if _should_stop(stop_event):
                return
            msg_queue.put(msg)

        try:
            if virtual:
                log_status("Creating virtual MIDI input: '%s'", target_port)
            with open_port(target_port, callback=on_midi, virtual=virtual):
                log_status("Listening on MIDI: '%s'", target_port)
                next_port_check = time.monotonic() + PORT_CHECK_S
                while not _should_stop(stop_event):
                    try:
                        msg = msg_queue.get(timeout=QUEUE_POLL_S)
                    except queue.Empty:
                        if not virtual and time.monotonic() >= next_port_check:
                            if target_port not in get_names():
                                raise MidiPortDisconnected(
                                    f"MIDI port '{target_port}' disconnected"
                                )
                            next_port_check = time.monotonic() + PORT_CHECK_S
                        continue

                    muted = mute_event is not None and mute_event.is_set()
                    _dispatch_message(
                        msg,
                        mappings,
                        convert_unmapped,
                        client,
                        osc_stats,
                        muted,
                        listen_channels,
                    )

        except MidiPortConfigError:
            raise
        except MidiPortDisconnected as exc:
            if _should_stop(stop_event):
                return
            if not reconnect:
                raise
            logger.error(
                "MIDI connection lost (%s); reconnecting in %.1fs...",
                exc,
                RECONNECT_WAIT_S,
            )
            _drain_queue(msg_queue)
            if _wait_idle(stop_event, RECONNECT_WAIT_S):
                return
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
            _drain_queue(msg_queue)
            if _wait_idle(stop_event, RECONNECT_WAIT_S):
                return


def run_from_config(
    config: AppConfig,
    stop_event: Optional[threading.Event] = None,
    *,
    reconnect: bool = True,
    mute_event: Optional[threading.Event] = None,
) -> None:
    """Run the converter using a parsed AppConfig."""
    log_status("Target OSC: %s:%s", config.ip, config.port)
    log_status("Convert unmapped: %s", config.convert_unmapped)
    log_status("Virtual MIDI port: %s", config.virtual)
    log_status("Listening on MIDI channel: %s", format_channels(config.listen_channels))
    log_status("Mappings loaded: %s", len(config.mappings))
    log_status(
        "OSC output: %s",
        "MUTED" if mute_event is not None and mute_event.is_set() else "live",
    )

    run_converter(
        config.midi_port,
        config.ip,
        config.port,
        config.mappings,
        stop_event=stop_event,
        convert_unmapped=config.convert_unmapped,
        virtual=config.virtual,
        reconnect=reconnect,
        listen_channels=config.listen_channels,
        mute_event=mute_event,
    )


def run_from_config_path(
    config_path: Path,
    stop_event: Optional[threading.Event] = None,
    *,
    reconnect: bool = True,
    mute_event: Optional[threading.Event] = None,
) -> AppConfig:
    """Parse config from disk and run the converter. Returns the config used."""
    config = parse_config(config_path)
    log_status("Active config: %s", config_path.name)
    run_from_config(
        config,
        stop_event=stop_event,
        reconnect=reconnect,
        mute_event=mute_event,
    )
    return config

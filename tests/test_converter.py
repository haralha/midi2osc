"""Unit tests for MIDI routing and port resolution."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from midi2osc.converter import MidiPortError, resolve_midi_port, route_midi_message, run_converter


def test_note_on_velocity_zero_becomes_note_off_default() -> None:
    msg = SimpleNamespace(type="note_on", channel=0, note=60, velocity=0)
    routed = route_midi_message(msg, mappings={}, convert_unmapped=True)
    assert routed is not None
    assert routed.osc_address == "/midi/channel/0/note_off"
    assert routed.value == [60, 0]
    assert routed.mapped is False
    assert routed.send is True


def test_note_on_and_note_off_share_note_mapping() -> None:
    mappings = {("note_on", 0, 60): "/clip/start"}
    on_msg = SimpleNamespace(type="note_on", channel=0, note=60, velocity=100)
    off_msg = SimpleNamespace(type="note_off", channel=0, note=60, velocity=64)
    on = route_midi_message(on_msg, mappings)
    off = route_midi_message(off_msg, mappings)
    assert on is not None and off is not None
    assert on.mapped and off.mapped
    assert on.osc_address == off.osc_address == "/clip/start"
    assert on.value == 100
    assert off.value == 0


def test_unmapped_logged_only_when_disabled() -> None:
    msg = SimpleNamespace(type="control_change", channel=1, control=7, value=64)
    routed = route_midi_message(msg, mappings={}, convert_unmapped=False)
    assert routed is not None
    assert routed.send is False
    assert routed.mapped is False


def test_cc_and_program_defaults() -> None:
    cc = route_midi_message(
        SimpleNamespace(type="control_change", channel=2, control=10, value=33),
        {},
    )
    pc = route_midi_message(
        SimpleNamespace(type="program_change", channel=2, program=5),
        {},
    )
    assert cc is not None and pc is not None
    assert cc.osc_address == "/midi/channel/2/cc/10"
    assert cc.value == 33
    assert pc.osc_address == "/midi/channel/2/program_change"
    assert pc.value == 5


def test_resolve_exact_and_case_insensitive() -> None:
    ports = ["IAC Driver Bus 1", "Launchpad Mini"]
    assert resolve_midi_port("IAC Driver Bus 1", ports) == "IAC Driver Bus 1"
    assert resolve_midi_port("launchpad mini", ports) == "Launchpad Mini"


def test_resolve_unique_substring() -> None:
    ports = ["IAC Driver Bus 1", "Launchpad Mini"]
    assert resolve_midi_port("Launchpad", ports) == "Launchpad Mini"


def test_resolve_ambiguous_substring() -> None:
    ports = ["Bus 1", "Bus 2"]
    with pytest.raises(MidiPortError, match="ambiguous"):
        resolve_midi_port("Bus", ports)


def test_resolve_missing() -> None:
    with pytest.raises(MidiPortError, match="not found"):
        resolve_midi_port("Nope", ["Other"])


class _FakeMidiPort:
    def __init__(self, callback=None) -> None:
        self.callback = callback
        self.closed = False

    def __enter__(self) -> "_FakeMidiPort":
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True
        self.callback = None


def _start_converter(**kwargs):
    stop = kwargs.pop("stop_event", None) or threading.Event()
    thread = threading.Thread(
        target=run_converter,
        kwargs={"stop_event": stop, **kwargs},
        daemon=True,
    )
    thread.start()
    return stop, thread


def test_midi_callback_sends_osc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("midi2osc.converter.PORT_CHECK_S", 0.05)
    client = MagicMock()
    opened: dict[str, _FakeMidiPort] = {}

    def open_input(name: str, callback=None) -> _FakeMidiPort:
        port = _FakeMidiPort(callback=callback)
        opened["port"] = port
        return port

    stop, thread = _start_converter(
        port_name="IAC",
        osc_ip="127.0.0.1",
        osc_port=8000,
        mappings={("note_on", 0, 60): "/clip/start"},
        reconnect=False,
        client_factory=lambda ip, port: client,
        open_input=open_input,
        list_inputs=lambda: ["IAC"],
    )
    try:
        deadline = time.monotonic() + 2.0
        while "port" not in opened and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "port" in opened
        opened["port"].callback(
            SimpleNamespace(type="note_on", channel=0, note=60, velocity=100)
        )
        client.send_message.assert_called_once_with("/clip/start", 100)
    finally:
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


def test_callback_reconnects_when_port_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("midi2osc.converter.PORT_CHECK_S", 0.05)
    monkeypatch.setattr("midi2osc.converter.RECONNECT_WAIT_S", 0.05)
    opens = 0
    disconnected = False

    def open_input(name: str, callback=None) -> _FakeMidiPort:
        nonlocal opens
        opens += 1
        return _FakeMidiPort(callback=callback)

    def list_inputs() -> list[str]:
        nonlocal disconnected
        if opens == 1 and not disconnected:
            disconnected = True
            return []
        return ["IAC"]

    stop, thread = _start_converter(
        port_name="IAC",
        osc_ip="127.0.0.1",
        osc_port=8000,
        mappings={},
        reconnect=True,
        client_factory=lambda ip, port: MagicMock(),
        open_input=open_input,
        list_inputs=list_inputs,
    )
    try:
        deadline = time.monotonic() + 2.0
        while opens < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert opens >= 2
    finally:
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()

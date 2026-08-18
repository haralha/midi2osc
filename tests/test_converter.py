"""Unit tests for MIDI routing and port resolution."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from midi2osc.config import MappingKey, OscMapping
from midi2osc.converter import MidiPortError, resolve_midi_port, route_midi_message, run_converter


def test_note_on_velocity_zero_becomes_note_off_default() -> None:
    msg = SimpleNamespace(type="note_on", channel=0, note=60, velocity=0)
    routed = route_midi_message(msg, mappings={}, convert_unmapped=True)
    assert routed is not None
    assert routed.osc_address == "/midi/channel/1/note_off"
    assert routed.midi_sig == "note_off 1 60"
    assert routed.value == [60, 0]
    assert routed.mapped is False
    assert routed.send is True


def test_note_on_and_note_off_share_note_mapping() -> None:
    mappings = {MappingKey("note_on", 0, 60): OscMapping("/clip/start")}
    on_msg = SimpleNamespace(type="note_on", channel=0, note=60, velocity=100)
    off_msg = SimpleNamespace(type="note_off", channel=0, note=60, velocity=64)
    on = route_midi_message(on_msg, mappings)
    off = route_midi_message(off_msg, mappings)
    assert on is not None and off is not None
    assert on.mapped and off.mapped
    assert on.osc_address == off.osc_address == "/clip/start"
    assert on.midi_sig == "note_on 1 60"
    assert off.midi_sig == "note_off 1 60"
    assert on.value == 100
    assert off.value == 0


def test_mapped_value_expression_float_and_static() -> None:
    mappings = {
        MappingKey("control_change", 0, 7): OscMapping("/volume", "v/127"),
        MappingKey("note_on", 0, 60): OscMapping("/clip/connect", "1"),
    }
    cc = route_midi_message(
        SimpleNamespace(type="control_change", channel=0, control=7, value=127),
        mappings,
    )
    note = route_midi_message(
        SimpleNamespace(type="note_on", channel=0, note=60, velocity=100),
        mappings,
    )
    assert cc is not None and note is not None
    assert cc.send and cc.value == 1.0
    assert isinstance(cc.value, float)
    assert note.send and note.value == 1
    assert isinstance(note.value, int)


def test_mapped_value_expression_string() -> None:
    mappings = {MappingKey("program_change", 0, 1): OscMapping("/qlab/start", '"cue_{v}"')}
    routed = route_midi_message(
        SimpleNamespace(type="program_change", channel=0, program=1),
        mappings,
    )
    assert routed is not None
    assert routed.send is True
    assert routed.value == "cue_1"


def test_bad_runtime_expression_skips_send() -> None:
    mappings = {MappingKey("control_change", 0, 7): OscMapping("/volume", "v / 0")}
    routed = route_midi_message(
        SimpleNamespace(type="control_change", channel=0, control=7, value=10),
        mappings,
    )
    assert routed is not None
    assert routed.mapped is True
    assert routed.send is False


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
    assert cc.osc_address == "/midi/channel/3/cc/10"
    assert cc.value == 33
    assert pc.osc_address == "/midi/channel/3/program_change"
    assert pc.value == 5


def test_channel_filter_drops_other_channels() -> None:
    listen = frozenset({4})
    on_channel = route_midi_message(
        SimpleNamespace(type="control_change", channel=4, control=7, value=64),
        {},
        True,
        listen,
    )
    off_channel = route_midi_message(
        SimpleNamespace(type="control_change", channel=0, control=7, value=64),
        {},
        True,
        listen,
    )
    assert on_channel is not None
    assert on_channel.osc_address == "/midi/channel/5/cc/7"
    assert off_channel is None


def test_channel_filter_always_passes_sysex() -> None:
    routed = route_midi_message(
        SimpleNamespace(type="sysex", data=[1, 2, 3]),
        {},
        True,
        frozenset({4}),
    )
    assert routed is not None
    assert routed.osc_address == "/midi/sysex"


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


def test_resolve_missing_includes_config_hint() -> None:
    with pytest.raises(MidiPortError, match="Update midi_port"):
        resolve_midi_port("Nope", ["IAC Driver Bus 1"])


def test_unknown_port_does_not_reconnect() -> None:
    calls = {"n": 0}

    def list_inputs() -> list[str]:
        calls["n"] += 1
        return ["IAC Driver Bus 1"]

    with pytest.raises(MidiPortError, match="not found"):
        run_converter(
            port_name="Nope",
            osc_ip="127.0.0.1",
            osc_port=8000,
            mappings={},
            reconnect=True,
            list_inputs=list_inputs,
        )
    assert calls["n"] == 1


def test_runtime_does_not_reparse_value_expr(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = OscMapping("/volume", "v/127")
    assert mapping.compiled_expr is not None

    def boom(_src: str) -> None:
        raise AssertionError("value expressions must not be reparsed on the hot path")

    monkeypatch.setattr("midi2osc.expr.parse_value_expr", boom)
    monkeypatch.setattr("midi2osc.config.parse_value_expr", boom)

    routed = route_midi_message(
        SimpleNamespace(type="control_change", channel=0, control=7, value=127),
        {MappingKey("control_change", 0, 7): mapping},
    )
    assert routed is not None
    assert routed.send is True
    assert routed.value == 1.0


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


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
    monkeypatch.setattr("midi2osc.converter.QUEUE_POLL_S", 0.01)
    client = MagicMock()
    opened: dict[str, object] = {}

    def open_input(name: str, callback=None, *, virtual: bool = False) -> _FakeMidiPort:
        port = _FakeMidiPort(callback=callback)
        opened["port"] = port
        opened["virtual"] = virtual
        return port

    stop, thread = _start_converter(
        port_name="IAC",
        osc_ip="127.0.0.1",
        osc_port=8000,
        mappings={MappingKey("note_on", 0, 60): OscMapping("/clip/start")},
        reconnect=False,
        client_factory=lambda ip, port: client,
        open_input=open_input,
        list_inputs=lambda: ["IAC"],
    )
    try:
        _wait_until(lambda: "port" in opened)
        assert opened["virtual"] is False
        port = opened["port"]
        assert isinstance(port, _FakeMidiPort)
        port.callback(SimpleNamespace(type="note_on", channel=0, note=60, velocity=100))
        _wait_until(lambda: client.send_message.called)
        client.send_message.assert_called_once_with("/clip/start", 100)
    finally:
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


def test_mute_event_blocks_osc_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("midi2osc.converter.PORT_CHECK_S", 0.05)
    monkeypatch.setattr("midi2osc.converter.QUEUE_POLL_S", 0.01)
    client = MagicMock()
    mute = threading.Event()
    mute.set()
    opened: dict[str, object] = {}

    def open_input(name: str, callback=None, *, virtual: bool = False) -> _FakeMidiPort:
        port = _FakeMidiPort(callback=callback)
        opened["port"] = port
        return port

    stop, thread = _start_converter(
        port_name="IAC",
        osc_ip="127.0.0.1",
        osc_port=8000,
        mappings={MappingKey("note_on", 0, 60): OscMapping("/clip/start")},
        reconnect=False,
        mute_event=mute,
        client_factory=lambda ip, port: client,
        open_input=open_input,
        list_inputs=lambda: ["IAC"],
    )
    try:
        _wait_until(lambda: "port" in opened)
        port = opened["port"]
        assert isinstance(port, _FakeMidiPort)

        msg = SimpleNamespace(type="note_on", channel=0, note=60, velocity=100)
        port.callback(msg)
        time.sleep(0.08)
        client.send_message.assert_not_called()

        # Unmuting takes effect without reopening the port.
        mute.clear()
        port.callback(msg)
        _wait_until(lambda: client.send_message.called)
        client.send_message.assert_called_once_with("/clip/start", 100)
    finally:
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


def test_virtual_port_opens_without_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("midi2osc.converter.PORT_CHECK_S", 0.05)
    monkeypatch.setattr("midi2osc.ports.sys.platform", "darwin")
    opened: dict[str, object] = {}

    def open_input(name: str, callback=None, *, virtual: bool = False) -> _FakeMidiPort:
        opened["name"] = name
        opened["virtual"] = virtual
        return _FakeMidiPort(callback=callback)

    stop, thread = _start_converter(
        port_name="MIDI2OSC Bridge",
        osc_ip="127.0.0.1",
        osc_port=8000,
        mappings={},
        virtual=True,
        reconnect=False,
        client_factory=lambda ip, port: MagicMock(),
        open_input=open_input,
        list_inputs=lambda: [],  # must not be consulted for name resolution
    )
    try:
        _wait_until(lambda: "name" in opened)
        assert opened["name"] == "MIDI2OSC Bridge"
        assert opened["virtual"] is True
    finally:
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


def test_virtual_port_rejected_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("midi2osc.ports.sys.platform", "win32")
    with pytest.raises(MidiPortError, match="not supported on Windows"):
        run_converter(
            port_name="MIDI2OSC Bridge",
            osc_ip="127.0.0.1",
            osc_port=8000,
            mappings={},
            virtual=True,
            reconnect=False,
            list_inputs=lambda: [],
        )


def test_channel_filter_blocks_osc_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("midi2osc.converter.PORT_CHECK_S", 0.05)
    monkeypatch.setattr("midi2osc.converter.QUEUE_POLL_S", 0.01)
    client = MagicMock()
    opened: dict[str, object] = {}

    def open_input(name: str, callback=None, *, virtual: bool = False) -> _FakeMidiPort:
        port = _FakeMidiPort(callback=callback)
        opened["port"] = port
        return port

    stop, thread = _start_converter(
        port_name="IAC",
        osc_ip="127.0.0.1",
        osc_port=8000,
        mappings={
            MappingKey("note_on", 0, 60): OscMapping("/ch1"),
            MappingKey("note_on", 1, 60): OscMapping("/ch2"),
        },
        reconnect=False,
        listen_channels=frozenset({1}),
        client_factory=lambda ip, port: client,
        open_input=open_input,
        list_inputs=lambda: ["IAC"],
    )
    try:
        _wait_until(lambda: "port" in opened)
        port = opened["port"]
        assert isinstance(port, _FakeMidiPort)

        port.callback(SimpleNamespace(type="note_on", channel=0, note=60, velocity=100))
        time.sleep(0.08)
        client.send_message.assert_not_called()

        port.callback(SimpleNamespace(type="note_on", channel=1, note=60, velocity=100))
        _wait_until(lambda: client.send_message.called)
        client.send_message.assert_called_once_with("/ch2", 100)
    finally:
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()


def test_callback_reconnects_when_port_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("midi2osc.converter.PORT_CHECK_S", 0.05)
    monkeypatch.setattr("midi2osc.converter.QUEUE_POLL_S", 0.01)
    monkeypatch.setattr("midi2osc.converter.RECONNECT_WAIT_S", 0.05)
    opens = 0
    disconnected = False

    def open_input(name: str, callback=None, *, virtual: bool = False) -> _FakeMidiPort:
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
        _wait_until(lambda: opens >= 2)
        assert opens >= 2
    finally:
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()

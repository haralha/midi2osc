"""Unit tests for MIDI routing and port resolution."""

from types import SimpleNamespace

import pytest

from midi2osc.converter import MidiPortError, resolve_midi_port, route_midi_message


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

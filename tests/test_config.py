"""Unit tests for config parsing."""

from pathlib import Path

import pytest

from midi2osc.config import (
    ALL_CHANNELS,
    ALL_EVENTS,
    MappingKey,
    OscMapping,
    example_config_text,
    format_channels,
    format_events,
    parse_channel_spec,
    parse_config,
    parse_event_spec,
)


def test_parse_basic_settings_and_mappings(tmp_path: Path) -> None:
    path = tmp_path / "test.mapping.txt"
    path.write_text(
        """
ip = 10.0.0.5
port = 9000
midi_port = "IAC Driver Bus 1"
convert_unmapped = false
virtual = true

note 1 60 -> /clip/1
cc 1 7 -> /volume
pc 2 3 -> /program
sysex -> /midi/sysex
""",
        encoding="utf-8",
    )

    cfg = parse_config(path)
    assert cfg.ip == "10.0.0.5"
    assert cfg.port == 9000
    assert cfg.midi_port == "IAC Driver Bus 1"
    assert cfg.convert_unmapped is False
    assert cfg.virtual is True
    # Config channels are 1-16; stored 0-based to match mido
    assert cfg.mappings[MappingKey("note_on", 0, 60)] == OscMapping("/clip/1")
    assert cfg.mappings[MappingKey("control_change", 0, 7)] == OscMapping("/volume")
    assert cfg.mappings[MappingKey("program_change", 1, 3)] == OscMapping("/program")
    assert cfg.mappings[MappingKey("sysex", None, None)] == OscMapping("/midi/sysex")
    # NamedTuple keys still compare equal to plain tuples.
    assert ("note_on", 0, 60) in cfg.mappings


def test_parse_value_expressions(tmp_path: Path) -> None:
    path = tmp_path / "expr.mapping.txt"
    path.write_text(
        """
cc 1 7 -> /composition/master/volume v/127
cc 1 10 -> /light/brightness 1 - (v/127)
note 1 60 -> /clip/connect 1
pc 1 1 -> /qlab/cue/start "cue_{v}"
note 1 1 -> /gma3/cmd "Speedmaster 3.1 At {v+50}; FastSync Speedmaster 3.1"
""",
        encoding="utf-8",
    )
    cfg = parse_config(path)
    assert cfg.mappings[MappingKey("control_change", 0, 7)] == OscMapping(
        "/composition/master/volume", "v/127"
    )
    assert cfg.mappings[MappingKey("control_change", 0, 10)] == OscMapping(
        "/light/brightness", "1 - (v/127)"
    )
    assert cfg.mappings[MappingKey("note_on", 0, 60)] == OscMapping("/clip/connect", "1")
    assert cfg.mappings[MappingKey("program_change", 0, 1)] == OscMapping(
        "/qlab/cue/start", '"cue_{v}"'
    )
    assert cfg.mappings[MappingKey("note_on", 0, 1)] == OscMapping(
        "/gma3/cmd",
        '"Speedmaster 3.1 At {v+50}; FastSync Speedmaster 3.1"',
    )
    compiled = cfg.mappings[MappingKey("control_change", 0, 7)].compiled_expr
    assert compiled is not None


def test_rejects_invalid_value_expression(tmp_path: Path) -> None:
    path = tmp_path / "bad-expr.mapping.txt"
    path.write_text("cc 1 7 -> /volume __import__('os')\n", encoding="utf-8")
    cfg = parse_config(path)
    assert cfg.mappings == {}


def test_rejects_sysex_value_expression(tmp_path: Path) -> None:
    path = tmp_path / "sysex-expr.mapping.txt"
    path.write_text("sysex -> /midi/sysex v\n", encoding="utf-8")
    cfg = parse_config(path)
    assert cfg.mappings == {}


def test_aliases_and_section_headers(tmp_path: Path) -> None:
    path = tmp_path / "aliases.mapping.txt"
    path.write_text(
        """
--- NETWORK ---
host: 127.0.0.1
osc_port: 7700
midi: Device A

--- MAPPINGS ---
note_on 3 10 -> /a
control 3 11 -> /b
program 3 12 -> /c
""",
        encoding="utf-8",
    )
    cfg = parse_config(path)
    assert cfg.ip == "127.0.0.1"
    assert cfg.port == 7700
    assert cfg.midi_port == "Device A"
    assert ("note_on", 2, 10) in cfg.mappings
    assert ("control_change", 2, 11) in cfg.mappings
    assert ("program_change", 2, 12) in cfg.mappings
    note_key = next(k for k in cfg.mappings if k.msg_type == "note_on")
    assert note_key.channel == 2
    assert note_key.number == 10


def test_rejects_out_of_range_channel(tmp_path: Path) -> None:
    path = tmp_path / "bad.mapping.txt"
    path.write_text(
        "note 0 60 -> /x\nnote 17 60 -> /y\n",
        encoding="utf-8",
    )
    cfg = parse_config(path)
    assert cfg.mappings == {}


def test_accepts_channel_16(tmp_path: Path) -> None:
    path = tmp_path / "ch16.mapping.txt"
    path.write_text("cc 16 7 -> /volume\n", encoding="utf-8")
    cfg = parse_config(path)
    assert cfg.mappings[MappingKey("control_change", 15, 7)] == OscMapping("/volume")


def test_with_overrides() -> None:
    from midi2osc.config import AppConfig

    base = AppConfig(
        ip="1.1.1.1",
        port=1,
        midi_port="A",
        convert_unmapped=False,
        virtual=True,
    )
    updated = base.with_overrides(
        ip="2.2.2.2",
        midi_port="B",
        virtual=False,
        listen_channels=frozenset({3}),
        listen_events=frozenset({"control_change"}),
    )
    assert updated.ip == "2.2.2.2"
    assert updated.port == 1
    assert updated.midi_port == "B"
    assert updated.convert_unmapped is False
    assert updated.virtual is False
    assert updated.listen_channels == frozenset({3})
    assert updated.listen_events == frozenset({"control_change"})
    assert base.virtual is True
    assert base.listen_channels == ALL_CHANNELS
    assert base.listen_events == ALL_EVENTS


def test_listen_channels_default_to_all(tmp_path: Path) -> None:
    path = tmp_path / "no-channel.mapping.txt"
    path.write_text("cc 1 7 -> /volume\n", encoding="utf-8")
    assert parse_config(path).listen_channels == ALL_CHANNELS


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("all", ALL_CHANNELS),
        ("ALL", ALL_CHANNELS),
        ("*", ALL_CHANNELS),
        ("5", {4}),
        ("1,3,9", {0, 2, 8}),
        ("1-4, 16", {0, 1, 2, 3, 15}),
        ("2-2", {1}),
    ],
)
def test_parse_channel_spec(spec: str, expected: set[int]) -> None:
    assert parse_channel_spec(spec) == frozenset(expected)


@pytest.mark.parametrize("spec", ["", "0", "17", "abc", "4-2", "1,,2", "1-"])
def test_parse_channel_spec_rejects_invalid(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_channel_spec(spec)


def test_channel_setting_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "channel.mapping.txt"
    path.write_text("channel = 1-3, 10\ncc 1 7 -> /volume\n", encoding="utf-8")
    assert parse_config(path).listen_channels == frozenset({0, 1, 2, 9})


def test_channel_aliases(tmp_path: Path) -> None:
    path = tmp_path / "channel-alias.mapping.txt"
    path.write_text("midi_channel: 5\n", encoding="utf-8")
    assert parse_config(path).listen_channels == frozenset({4})


def test_invalid_channel_setting_keeps_all(tmp_path: Path, caplog) -> None:
    path = tmp_path / "bad-channel.mapping.txt"
    path.write_text("channel = 20\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="midi2osc"):
        cfg = parse_config(path)
    assert cfg.listen_channels == ALL_CHANNELS
    assert any("channel must be 1-16" in rec.getMessage() for rec in caplog.records)


def test_warns_about_mappings_outside_listen_channels(tmp_path: Path, caplog) -> None:
    path = tmp_path / "unreachable.mapping.txt"
    path.write_text(
        "channel = 1\ncc 1 7 -> /volume\ncc 4 7 -> /other\nsysex -> /midi/sysex\n",
        encoding="utf-8",
    )
    with caplog.at_level("WARNING", logger="midi2osc"):
        cfg = parse_config(path)
    assert len(cfg.mappings) == 3
    assert any("can never trigger" in rec.getMessage() for rec in caplog.records)


@pytest.mark.parametrize(
    ("channels", "expected"),
    [
        (ALL_CHANNELS, "all"),
        (frozenset(), "none"),
        (frozenset({4}), "5"),
        (frozenset({0, 2, 4, 5, 6, 7}), "1, 3, 5-8"),
    ],
)
def test_format_channels(channels: frozenset[int], expected: str) -> None:
    assert format_channels(channels) == expected


def test_listen_events_default_to_all(tmp_path: Path) -> None:
    path = tmp_path / "no-events.mapping.txt"
    path.write_text("cc 1 7 -> /volume\n", encoding="utf-8")
    assert parse_config(path).listen_events == ALL_EVENTS


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("all", ALL_EVENTS),
        ("any", ALL_EVENTS),
        ("*", ALL_EVENTS),
        ("note", {"note_on", "note_off"}),
        ("notes", {"note_on", "note_off"}),
        ("note_on", {"note_on"}),
        ("NOTE_OFF", {"note_off"}),
        ("cc", {"control_change"}),
        ("control_change", {"control_change"}),
        ("pc", {"program_change"}),
        ("sysex", {"sysex"}),
        ("note_on, cc", {"note_on", "control_change"}),
        ("note,pc", {"note_on", "note_off", "program_change"}),
    ],
)
def test_parse_event_spec(spec: str, expected: set[str]) -> None:
    assert parse_event_spec(spec) == frozenset(expected)


@pytest.mark.parametrize("spec", ["", "pitchwheel", "note_on,,cc", "cc pc", "1"])
def test_parse_event_spec_rejects_invalid(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_event_spec(spec)


def test_events_setting_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "events.mapping.txt"
    path.write_text("events = note_on, cc\ncc 1 7 -> /volume\n", encoding="utf-8")
    assert parse_config(path).listen_events == frozenset({"note_on", "control_change"})


def test_events_aliases(tmp_path: Path) -> None:
    path = tmp_path / "events-alias.mapping.txt"
    path.write_text("message_types: sysex\n", encoding="utf-8")
    assert parse_config(path).listen_events == frozenset({"sysex"})


def test_invalid_events_setting_keeps_all(tmp_path: Path, caplog) -> None:
    path = tmp_path / "bad-events.mapping.txt"
    path.write_text("events = pitchwheel\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="midi2osc"):
        cfg = parse_config(path)
    assert cfg.listen_events == ALL_EVENTS
    assert any("unknown event" in rec.getMessage() for rec in caplog.records)


def test_warns_about_mappings_outside_listen_events(tmp_path: Path, caplog) -> None:
    path = tmp_path / "unreachable-events.mapping.txt"
    path.write_text(
        "events = cc\nnote 1 60 -> /clip\ncc 1 7 -> /volume\n",
        encoding="utf-8",
    )
    with caplog.at_level("WARNING", logger="midi2osc"):
        cfg = parse_config(path)
    assert len(cfg.mappings) == 2
    assert any(
        "Mappings for note_on can never trigger" in rec.getMessage()
        for rec in caplog.records
    )


def test_note_mapping_reachable_when_only_note_off_is_listened_for(
    tmp_path: Path, caplog
) -> None:
    path = tmp_path / "note-off.mapping.txt"
    path.write_text("events = note_off\nnote 1 60 -> /clip\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="midi2osc"):
        parse_config(path)
    assert not any("can never trigger" in rec.getMessage() for rec in caplog.records)


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        (ALL_EVENTS, "all"),
        (frozenset(), "none"),
        (frozenset({"control_change"}), "cc"),
        (frozenset({"note_on", "note_off"}), "note_on, note_off"),
        (frozenset({"program_change", "note_on"}), "note_on, pc"),
    ],
)
def test_format_events(events: frozenset[str], expected: str) -> None:
    assert format_events(events) == expected


def test_ignored_lines_are_summarized(tmp_path: Path, caplog) -> None:
    path = tmp_path / "ignored.mapping.txt"
    path.write_text(
        "note 0 60 -> /x\nnot a mapping or setting\n",
        encoding="utf-8",
    )
    with caplog.at_level("WARNING", logger="midi2osc"):
        cfg = parse_config(path)
    assert cfg.mappings == {}
    assert any("ignored line(s)" in rec.getMessage() for rec in caplog.records)




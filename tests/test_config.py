"""Unit tests for config parsing."""

from pathlib import Path

from midi2osc.config import MappingKey, OscMapping, example_config_text, parse_config


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
    updated = base.with_overrides(ip="2.2.2.2", midi_port="B", virtual=False)
    assert updated.ip == "2.2.2.2"
    assert updated.port == 1
    assert updated.midi_port == "B"
    assert updated.convert_unmapped is False
    assert updated.virtual is False
    assert base.virtual is True


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




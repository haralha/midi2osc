"""Unit tests for config parsing."""

from pathlib import Path

from midi2osc.config import parse_config


def test_parse_basic_settings_and_mappings(tmp_path: Path) -> None:
    path = tmp_path / "test.mapping.txt"
    path.write_text(
        """
ip = 10.0.0.5
port = 9000
midi_port = "IAC Driver Bus 1"
convert_unmapped = false

note 0 60 -> /clip/1
cc 0 7 -> /volume
pc 1 3 -> /program
sysex -> /midi/sysex
""",
        encoding="utf-8",
    )

    cfg = parse_config(path)
    assert cfg.ip == "10.0.0.5"
    assert cfg.port == 9000
    assert cfg.midi_port == "IAC Driver Bus 1"
    assert cfg.convert_unmapped is False
    assert cfg.mappings[("note_on", 0, 60)] == "/clip/1"
    assert cfg.mappings[("control_change", 0, 7)] == "/volume"
    assert cfg.mappings[("program_change", 1, 3)] == "/program"
    assert cfg.mappings[("sysex", None, None)] == "/midi/sysex"


def test_aliases_and_section_headers(tmp_path: Path) -> None:
    path = tmp_path / "aliases.mapping.txt"
    path.write_text(
        """
--- NETWORK ---
host: 127.0.0.1
osc_port: 7700
midi: Device A

--- MAPPINGS ---
note_on 2 10 -> /a
control 2 11 -> /b
program 2 12 -> /c
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


def test_rejects_out_of_range_channel(tmp_path: Path) -> None:
    path = tmp_path / "bad.mapping.txt"
    path.write_text("note 16 60 -> /x\n", encoding="utf-8")
    cfg = parse_config(path)
    assert cfg.mappings == {}


def test_with_overrides() -> None:
    from midi2osc.config import AppConfig

    base = AppConfig(ip="1.1.1.1", port=1, midi_port="A", convert_unmapped=False)
    updated = base.with_overrides(ip="2.2.2.2", midi_port="B")
    assert updated.ip == "2.2.2.2"
    assert updated.port == 1
    assert updated.midi_port == "B"
    assert updated.convert_unmapped is False

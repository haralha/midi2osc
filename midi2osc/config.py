"""Configuration file parser for MIDI to OSC Converter."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("midi2osc")

MappingKey = tuple[str, Optional[int], Optional[int]]

EXAMPLE_CONFIG = """# midi2osc Configuration File Example
# -----------------------------------------------
# Channels are 0-15 (MIDI channel 1 = 0 in this file).
# Notes/CC numbers are 0-127.
#
# MIDI Port / Device Name (exact name preferred; unique substring also works)
midi_port = "IAC Driver Bus 1"

# Target OSC Destination
ip = "127.0.0.1"
port = 8000

# Convert unmapped/fallback messages? (true/false)
# If false, messages without explicit mappings are only logged and NOT sent over OSC.
convert_unmapped = true

# MIDI to OSC Mappings
# Format: [MIDI_EVENT] [CHANNEL] [NOTE_OR_CC] -> [OSC_PATH]
#
# Event aliases:
#   note / note_on  -> note on AND note off (including note_on velocity 0)
#   cc / control    -> control_change
#   pc / program    -> program_change
#
# Examples:
# note 0 60 -> /resolume/layer1/clip1/connect
# cc 0 7 -> /composition/master/volume
# pc 0 1 -> /qlab/cue/1/start
"""


@dataclass
class AppConfig:
    """Parsed application configuration."""

    ip: str = "127.0.0.1"
    port: int = 7700
    midi_port: str = ""
    convert_unmapped: bool = True
    mappings: dict[MappingKey, str] = field(default_factory=dict)

    def with_overrides(
        self,
        *,
        ip: Optional[str] = None,
        port: Optional[int] = None,
        midi_port: Optional[str] = None,
        convert_unmapped: Optional[bool] = None,
    ) -> AppConfig:
        """Return a copy with optional CLI/runtime overrides applied."""
        return AppConfig(
            ip=ip if ip is not None else self.ip,
            port=port if port is not None else self.port,
            midi_port=midi_port if midi_port is not None else self.midi_port,
            convert_unmapped=(
                convert_unmapped
                if convert_unmapped is not None
                else self.convert_unmapped
            ),
            mappings=dict(self.mappings),
        )


def _normalize_msg_type(raw: str) -> str:
    token = raw.lower()
    if token in ("note", "note_on"):
        return "note_on"
    if token in ("cc", "control", "control_change"):
        return "control_change"
    if token in ("pc", "program", "program_change"):
        return "program_change"
    if token == "note_off":
        # note_off lines are accepted but share the note_on mapping bucket
        return "note_on"
    if token == "sysex":
        return "sysex"
    return token


def parse_config(config_path: Path) -> AppConfig:
    """Read and parse a mapping configuration file."""
    config = AppConfig()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            # Skip decorative section headers like "--- MAPPINGS ---"
            if line.startswith("---") and line.endswith("---"):
                continue

            if ("=" in line or ":" in line) and "->" not in line:
                delimiter = "=" if "=" in line else ":"
                key, val = line.split(delimiter, 1)
                key = key.strip().lower()
                val = val.strip().strip("'\"")

                if key in ("ip", "host"):
                    if not val:
                        logger.warning("Line %s: empty IP ignored", line_no)
                        continue
                    config.ip = val
                elif key in ("port", "osc_port"):
                    try:
                        port = int(val)
                    except ValueError:
                        logger.warning("Line %s: invalid PORT value: %s", line_no, line)
                        continue
                    if not (1 <= port <= 65535):
                        logger.warning("Line %s: PORT out of range 1-65535: %s", line_no, port)
                        continue
                    config.port = port
                elif key in ("midi_port", "midi_device", "midi"):
                    config.midi_port = val
                elif key in ("convert_unmapped", "convert_all", "passthrough"):
                    config.convert_unmapped = val.lower() in ("true", "1", "yes", "on")
                else:
                    logger.warning("Line %s: unknown setting '%s'", line_no, key)

            elif "->" in line:
                left, osc_address = line.split("->", 1)
                osc_address = osc_address.strip()
                parts = left.strip().split()

                if not osc_address.startswith("/"):
                    logger.warning(
                        "Line %s: OSC address should start with '/': %s",
                        line_no,
                        line,
                    )

                if len(parts) == 1 and parts[0].lower() == "sysex":
                    key_tuple: MappingKey = ("sysex", None, None)
                    if key_tuple in config.mappings:
                        logger.warning("Line %s: duplicate mapping for sysex", line_no)
                    config.mappings[key_tuple] = osc_address
                    continue

                if len(parts) != 3:
                    logger.warning("Line %s: invalid mapping syntax: %s", line_no, line)
                    continue

                msg_type = _normalize_msg_type(parts[0])
                try:
                    channel = int(parts[1])
                    number = int(parts[2])
                except ValueError:
                    logger.warning("Line %s: invalid mapping values: %s", line_no, line)
                    continue

                if not (0 <= channel <= 15):
                    logger.warning(
                        "Line %s: channel must be 0-15 (got %s)", line_no, channel
                    )
                    continue
                if not (0 <= number <= 127):
                    logger.warning(
                        "Line %s: note/CC/program must be 0-127 (got %s)",
                        line_no,
                        number,
                    )
                    continue

                key_tuple = (msg_type, channel, number)
                if key_tuple in config.mappings:
                    logger.warning(
                        "Line %s: duplicate mapping for %s %s %s",
                        line_no,
                        msg_type,
                        channel,
                        number,
                    )
                config.mappings[key_tuple] = osc_address
            else:
                logger.warning("Line %s: unrecognized line: %s", line_no, line)

    return config

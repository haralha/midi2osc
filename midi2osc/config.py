"""Configuration file parser for MIDI to OSC Converter."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from midi2osc.expr import ExprError, parse_value_expr

logger = logging.getLogger("midi2osc")

MappingKey = tuple[str, Optional[int], Optional[int]]

EXAMPLE_CONFIG = """# midi2osc Configuration File Example
# -----------------------------------------------
# Channels are 1-16 (same numbering as most DAWs / controllers).
# Notes/CC numbers are 0-127.
#
# MIDI Port / Device Name (exact name preferred; unique substring also works)
midi_port = "MIDI2OSC Bridge"

# Create a virtual MIDI input port with that name? (true/false)
# macOS/Linux: mido creates the port so DAWs can send MIDI into this app.
# Windows: not supported — use loopMIDI (or similar) and set virtual = false.
virtual = true

# Target OSC Destination
ip = "127.0.0.1"
port = 8000

# Convert unmapped/fallback messages? (true/false)
# If false, messages without explicit mappings are only logged and NOT sent over OSC.
convert_unmapped = true

# MIDI to OSC Mappings
# Format: [MIDI_EVENT] [CHANNEL] [NOTE_OR_CC] -> [OSC_PATH] [OPTIONAL_VALUE_EXPR]
#
# Event aliases:
#   note / note_on  -> note on AND note off (including note_on velocity 0)
#   cc / control    -> control_change
#   pc / program    -> program_change
#
# Value expression (optional): use v for the incoming MIDI value (0-127).
#   (omit)              -> raw int 0-127
#   v/127               -> float 0.0-1.0
#   1                   -> static int
#   1 - (v/127)         -> inverted float
#   int(20 + v * 150)   -> scaled int
#   "cue_{v}"           -> string template
#
# Examples:
# note 1 60 -> /resolume/layer1/clip1/connect 1
# cc 1 7 -> /composition/master/volume v/127
# pc 1 1 -> /qlab/cue/1/start
"""


@dataclass(frozen=True)
class OscMapping:
    """OSC destination for a MIDI mapping key."""

    address: str
    value_expr: Optional[str] = None


@dataclass
class AppConfig:
    """Parsed application configuration."""

    ip: str = "127.0.0.1"
    port: int = 7700
    midi_port: str = ""
    convert_unmapped: bool = True
    virtual: bool = False
    mappings: dict[MappingKey, OscMapping] = field(default_factory=dict)

    def with_overrides(
        self,
        *,
        ip: Optional[str] = None,
        port: Optional[int] = None,
        midi_port: Optional[str] = None,
        convert_unmapped: Optional[bool] = None,
        virtual: Optional[bool] = None,
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
            virtual=virtual if virtual is not None else self.virtual,
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


def _parse_osc_rhs(rhs: str, line_no: int) -> Optional[OscMapping]:
    """Split OSC path and optional value expression from the right-hand side."""
    text = rhs.strip()
    if not text:
        logger.warning("Line %s: empty OSC destination", line_no)
        return None

    parts = text.split(None, 1)
    address = parts[0]
    value_expr = parts[1].strip() if len(parts) > 1 else None
    if value_expr == "":
        value_expr = None

    if not address.startswith("/"):
        logger.warning(
            "Line %s: OSC address should start with '/': %s",
            line_no,
            text,
        )

    if value_expr is not None:
        try:
            parse_value_expr(value_expr)
        except ExprError as exc:
            logger.warning(
                "Line %s: invalid value expression %r: %s",
                line_no,
                value_expr,
                exc,
            )
            return None

    return OscMapping(address=address, value_expr=value_expr)


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
                elif key in ("virtual", "virtual_port", "create_virtual"):
                    config.virtual = val.lower() in ("true", "1", "yes", "on")
                else:
                    logger.warning("Line %s: unknown setting '%s'", line_no, key)

            elif "->" in line:
                left, rhs = line.split("->", 1)
                mapping = _parse_osc_rhs(rhs, line_no)
                if mapping is None:
                    continue

                parts = left.strip().split()

                if len(parts) == 1 and parts[0].lower() == "sysex":
                    if mapping.value_expr is not None:
                        logger.warning(
                            "Line %s: value expressions are not supported for sysex",
                            line_no,
                        )
                        continue
                    key_tuple: MappingKey = ("sysex", None, None)
                    if key_tuple in config.mappings:
                        logger.warning("Line %s: duplicate mapping for sysex", line_no)
                    config.mappings[key_tuple] = mapping
                    continue

                if len(parts) != 3:
                    logger.warning("Line %s: invalid mapping syntax: %s", line_no, line)
                    continue

                msg_type = _normalize_msg_type(parts[0])
                try:
                    channel_1based = int(parts[1])
                    number = int(parts[2])
                except ValueError:
                    logger.warning("Line %s: invalid mapping values: %s", line_no, line)
                    continue

                if not (1 <= channel_1based <= 16):
                    logger.warning(
                        "Line %s: channel must be 1-16 (got %s)",
                        line_no,
                        channel_1based,
                    )
                    continue
                if not (0 <= number <= 127):
                    logger.warning(
                        "Line %s: note/CC/program must be 0-127 (got %s)",
                        line_no,
                        number,
                    )
                    continue

                # Store 0-based to match mido's msg.channel
                channel = channel_1based - 1
                key_tuple = (msg_type, channel, number)
                if key_tuple in config.mappings:
                    logger.warning(
                        "Line %s: duplicate mapping for %s %s %s",
                        line_no,
                        msg_type,
                        channel_1based,
                        number,
                    )
                config.mappings[key_tuple] = mapping
            else:
                logger.warning("Line %s: unrecognized line: %s", line_no, line)

    return config

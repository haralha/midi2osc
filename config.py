"""Configuration file parser module for MIDI to OSC Converter."""

from pathlib import Path

EXAMPLE_CONFIG = """# midi2osc Configuration File Example
# -----------------------------------------------
# MIDI Port / Device Name
midi_port = "Network Session 1"

# Target OSC Destination
ip = "127.0.0.1"
port = 8000

# Convert unmapped/fallback messages? (true/false)
# If set to false, messages without explicit mappings are only logged to terminal and NOT sent over OSC.
convert_unmapped = true

# MIDI to OSC Mappings
# Format: [MIDI_EVENT] [CHANNEL] [NOTE_OR_CC] -> [OSC_PATH]
# Examples:
# note_on 1 60 -> /trigger/note
# cc 1 7 -> /volume
"""


def parse_config(config_path: Path) -> dict:
    """Read and parse a mapping configuration file."""
    config: dict = {
        "ip": "127.0.0.1",
        "port": 7700,
        "midi_port": "",
        "convert_unmapped": True,
        "mappings": {},
    }

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and full-line comments
            if not line or line.startswith("#"):
                continue

            # Parse key-value settings
            if ("=" in line or ":" in line) and "->" not in line:
                delimiter = "=" if "=" in line else ":"
                key, val = line.split(delimiter, 1)
                key = key.strip().lower()
                val = val.strip().strip("'\"")

                if key in ("ip", "host"):
                    config["ip"] = val
                elif key in ("port", "osc_port"):
                    try:
                        config["port"] = int(val)
                    except ValueError:
                        print(f"Invalid PORT value in config: {line}")
                elif key in ("midi_port", "midi_device", "midi"):
                    config["midi_port"] = val
                elif key in ("convert_unmapped", "convert_all", "passthrough"):
                    config["convert_unmapped"] = val.lower() in ("true", "1", "yes", "on")

            # Parse mapping lines
            elif "->" in line:
                left, osc_address = line.split("->", 1)
                osc_address = osc_address.strip()
                parts = left.strip().split()

                if len(parts) == 3:
                    msg_type = (
                        "note_on" if parts[0].lower() == "note" else parts[0].lower()
                    )
                    msg_type = (
                        "control_change"
                        if msg_type in ("cc", "control")
                        else msg_type
                    )

                    try:
                        channel = int(parts[1])
                        number = int(parts[2])
                        config["mappings"][(msg_type, channel, number)] = osc_address
                    except ValueError:
                        print(f"Invalid config line: {line}")

    return config
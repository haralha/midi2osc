"""Configuration file finder and parser module."""

import sys
from pathlib import Path

DEFAULT_TXT_CONFIG = """# --- NETWORK SETTINGS ---
IP: 192.168.86.36
PORT: 7700
MIDI_PORT: 

# --- MAPPINGS ---
# Syntax: <type> <channel 0-15> <number 0-127> -> <OSC-path>
note 0 60 -> /resolume/layer1/clip1/connect
note 0 61 -> /qlab/cue/1/start
cc 0 7    -> /composition/master/volume
"""


def get_app_dir() -> Path:
    """Find the root directory where the executable or main script is located."""
    if getattr(sys, "frozen", False):
        exec_path = Path(sys.executable)
        # Håndterer macOS .app bundles (går ut av Contents/MacOS)
        if exec_path.parent.name == "MacOS" and "Contents" in exec_path.parts:
            return exec_path.parents[2].parent
        return exec_path.parent
    return Path(__file__).parent


def select_config_file() -> Path:
    """Search for *.mapping.txt files and return the active one."""
    app_dir = get_app_dir()
    config_files = sorted(list(app_dir.glob("*.mapping.txt")))
    legacy_config = app_dir / "mapping.txt"

    if legacy_config.exists() and legacy_config not in config_files:
        config_files.append(legacy_config)

    # 1. If no config files exist, create 'default.mapping.txt'
    if not config_files:
        default_file = app_dir / "default.mapping.txt"
        print(f"No config files found. Creating '{default_file.name}'...")
        with open(default_file, "w", encoding="utf-8") as f:
            f.write(DEFAULT_TXT_CONFIG)
        return default_file

    # 2. Return first found config file automatically in GUI context
    print(f"Loading active config: {config_files[0].name}")
    return config_files[0]


def parse_config(config_path: Path) -> dict:
    """Read and parse the selected mapping file."""
    config: dict = {
        "ip": "127.0.0.1",
        "port": 7700,
        "midi_port": "",
        "mappings": {}
    }

    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Network settings
            if line.upper().startswith("IP:"):
                config["ip"] = line.split(":", 1)[1].strip()
            elif line.upper().startswith("PORT:"):
                try:
                    config["port"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    print(f"Invalid PORT value in config: {line}")
            elif line.upper().startswith("MIDI_PORT:"):
                config["midi_port"] = line.split(":", 1)[1].strip()

            # Mapping lines (e.g.: note 0 60 -> /my/osc/path)
            elif "->" in line:
                left, osc_address = line.split("->", 1)
                osc_address = osc_address.strip()
                parts = left.strip().split()

                if len(parts) == 3:
                    msg_type = "note_on" if parts[0].lower() == "note" else parts[0].lower()
                    msg_type = "control_change" if msg_type in ("cc", "control") else msg_type

                    try:
                        channel = int(parts[1])
                        number = int(parts[2])
                        config["mappings"][(msg_type, channel, number)] = osc_address
                    except ValueError:
                        print(f"Invalid config line: {line}")

    return config
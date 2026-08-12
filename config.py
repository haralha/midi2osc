"""Configuration file finder and parser module."""

import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()

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
    """Find the directory where the executable or script is located."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def select_config_file() -> Path:
    """Search for *.mapping.txt files and prompt user to select one."""
    app_dir = get_app_dir()
    config_files = sorted(list(app_dir.glob("*.mapping.txt")))
    legacy_config = app_dir / "mapping.txt"

    if legacy_config.exists() and legacy_config not in config_files:
        config_files.append(legacy_config)

    # 1. If no config files exist, create 'default.mapping.txt'
    if not config_files:
        default_file = app_dir / "default.mapping.txt"
        console.print(f"[bold yellow]No config files found. Creating '{default_file.name}'...[/bold yellow]")
        with open(default_file, "w", encoding="utf-8") as f:
            f.write(DEFAULT_TXT_CONFIG)
        return default_file

    # 2. If only one config file exists, use it directly
    if len(config_files) == 1:
        console.print(f"[dim]Loading available config: {config_files[0].name}[/dim]")
        return config_files[0]

    # 3. If multiple config files exist, display selection menu
    table = Table(title="Available Configuration Files", show_header=True, header_style="bold cyan")
    table.add_column("Index", style="dim", width=6)
    table.add_column("Filename", style="bold")

    for i, file_path in enumerate(config_files):
        table.add_row(str(i), file_path.name)

    console.print(table)
    choice = input("\nSelect config file [default 0]: ").strip()
    index = int(choice) if choice.isdigit() and int(choice) < len(config_files) else 0
    return config_files[index]


def parse_config(config_path: Path) -> dict:
    """Read and parse the selected mapping file."""
    config = {
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
                config["port"] = int(line.split(":", 1)[1].strip())
            elif line.upper().startswith("MIDI_PORT:"):
                config["midi_port"] = line.split(":", 1)[1].strip()

            # Mapping lines (e.g.: note 0 60 -> /my/osc/path)
            elif "->" in line:
                left, osc_address = line.split("->")
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
                        console.print(f"[bold red]Invalid config line:[/bold red] {line}")

    return config
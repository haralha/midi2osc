"""CLI entrypoint for MIDI to OSC Converter."""

import argparse
import sys
from pathlib import Path
import mido
from colorama import init, Fore, Style

from config import parse_config
from converter import run_converter

# Initialize colorama (ensures ANSI color codes work on Windows, macOS, and Linux)
init(autoreset=True)

EXAMPLE_CONFIG = """# midi2osc Configuration File Example
# -----------------------------------------------
# MIDI Port / Device Name
midi_port = "Network Session 1"

# Target OSC Destination
ip = "127.0.0.1"
port = 8000

# MIDI to OSC Mappings
# Format: [MIDI_EVENT] [CHANNEL] [NOTE_OR_CC] -> [OSC_PATH]
# Examples:
# note_on 1 60 -> /trigger/note
# cc 1 7 -> /volume
"""


class ColorStream:
    """Wraps stdout to add terminal color formatting to converter log output."""

    def __init__(self, original_stdout):
        self.original_stdout = original_stdout

    def write(self, text):
        if not text.strip():
            self.original_stdout.write(text)
            return

        formatted = text

        # Highlight keywords in the terminal
        if "MIDI IN:" in formatted:
            formatted = formatted.replace(
                "MIDI IN:", f"{Fore.GREEN}{Style.BRIGHT}MIDI IN:{Style.RESET_ALL}"
            )
        if "MAPPED" in formatted:
            formatted = formatted.replace(
                "MAPPED", f"{Fore.GREEN}{Style.BRIGHT}MAPPED{Style.RESET_ALL}"
            )
        if "DEFAULT" in formatted:
            formatted = formatted.replace(
                "DEFAULT", f"{Fore.YELLOW}DEFAULT{Style.RESET_ALL}"
            )
        if any(k in formatted for k in ("Listening on MIDI", "Target OSC", "✔")):
            formatted = f"{Fore.CYAN}{formatted}{Style.RESET_ALL}"
        if any(k in formatted for k in ("Error", "Invalid", "✖")):
            formatted = f"{Fore.RED}{Style.BRIGHT}{formatted}{Style.RESET_ALL}"

        self.original_stdout.write(formatted)

    def flush(self):
        self.original_stdout.flush()


def list_midi_devices() -> None:
    """Prints all available MIDI input ports."""
    try:
        inputs = mido.get_input_names()
        print(f"{Fore.CYAN}Available MIDI Input Devices:{Style.RESET_ALL}")
        if not inputs:
            print("  (No MIDI input devices found)")
            return
        for name in inputs:
            print(f"  - {name}")
    except Exception as e:
        print(f"{Fore.RED}✖ Error querying MIDI devices: {e}{Style.RESET_ALL}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="High-Performance MIDI to OSC Converter CLI"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to mapping configuration file (*.mapping.txt)",
    )
    parser.add_argument(
        "-d",
        "--list-devices",
        action="store_true",
        help="List available MIDI input devices and exit",
    )
    parser.add_argument(
        "--example-config",
        action="store_true",
        help="Print an example mapping configuration file to stdout and exit",
    )
    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Create a 'default.mapping.txt' template in the current directory and exit",
    )

    args = parser.parse_args()

    # 1. List available MIDI devices
    if args.list_devices:
        list_midi_devices()
        sys.exit(0)

    # 2. Print example config template directly to stdout
    if args.example_config:
        print(EXAMPLE_CONFIG.strip())
        sys.exit(0)

    # 3. Generate a new default.mapping.txt if it does not exist
    if args.generate_config:
        out_path = Path("default.mapping.txt")
        if out_path.exists():
            print(
                f"{Fore.RED}✖ Error: 'default.mapping.txt' already exists in this directory.{Style.RESET_ALL}"
            )
            sys.exit(1)

        out_path.write_text(EXAMPLE_CONFIG.strip(), encoding="utf-8")
        print(f"{Fore.GREEN}✔ Created 'default.mapping.txt' successfully!{Style.RESET_ALL}")
        sys.exit(0)

    # 4. Resolve configuration file path
    if args.config:
        config_path = args.config
        if not config_path.exists():
            print(f"{Fore.RED}✖ Error: Config file '{config_path}' not found.{Style.RESET_ALL}")
            sys.exit(1)
    else:
        # Fallback to default.mapping.txt in the current working directory
        default_file = Path("default.mapping.txt")
        if default_file.exists():
            config_path = default_file
        else:
            print(
                f"{Fore.RED}✖ Error: No config file specified and 'default.mapping.txt' was not found.{Style.RESET_ALL}"
            )
            print("Usage: midi2osc -c <path/to/mapping.txt>")
            print("       midi2osc -d / --list-devices (to list available MIDI inputs)")
            print("       midi2osc --generate-config (to create a starting template)")
            sys.exit(1)

    # Enable color wrapper on stdout
    sys.stdout = ColorStream(sys.stdout)

    # Parse config and run converter
    try:
        config = parse_config(config_path)

        print(f"✔ Active config: {config_path.name}")
        print(f"Listening on MIDI: '{config['midi_port']}'")
        print(f"Target OSC: {config['ip']}:{config['port']}")
        print("Waiting for incoming MIDI events (Press Ctrl+C to exit)...")

        run_converter(
            config["midi_port"],
            config["ip"],
            config["port"],
            config["mappings"],
        )
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Stopping MIDI to OSC Converter. Goodbye!{Style.RESET_ALL}")
        sys.exit(0)
    except Exception as e:
        print(f"✖ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
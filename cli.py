"""CLI entrypoint for MIDI to OSC Converter."""

import argparse
import sys
from pathlib import Path
from colorama import init, Fore, Style

from config import parse_config, select_config_file, get_available_config_files
from converter import run_converter

# Initialiser colorama (sørger for at fargekoder fungerer på både Windows, Mac og Linux)
init(autoreset=True)


class ColorStream:
    """Wraps stdout to add terminal color formatting to converter log output."""

    def __init__(self, original_stdout):
        self.original_stdout = original_stdout

    def write(self, text):
        if not text.strip():
            self.original_stdout.write(text)
            return

        formatted = text

        # Fargelegg nøkkelord i terminalen
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

        # Fjernet + "\n" her for å unngå dobbel linjeavstand
        self.original_stdout.write(formatted)

    def flush(self):
        self.original_stdout.flush()


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
        "-l",
        "--list-configs",
        action="store_true",
        help="List available configuration files and exit",
    )

    args = parser.parse_args()

    # List configs if requested
    if args.list_configs:
        print(f"{Fore.CYAN}Available configuration files:{Style.RESET_ALL}")
        for cfg in get_available_config_files():
            print(f"  - {cfg}")
        sys.exit(0)

    # Resolve config file path
    if args.config:
        config_path = args.config
        if not config_path.exists():
            print(f"{Fore.RED}✖ Error: Config file '{config_path}' not found.{Style.RESET_ALL}")
            sys.exit(1)
    else:
        config_path = select_config_file()

    # Enable color wrapper on stdout
    sys.stdout = ColorStream(sys.stdout)

    # Parse config and start converter
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
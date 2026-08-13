"""CLI entrypoint for MIDI to OSC Converter."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import mido
from colorama import Fore, Style

from midi2osc.config import EXAMPLE_CONFIG, parse_config
from midi2osc.converter import MidiPortError, run_from_config
from midi2osc.logging_utils import setup_logging

logger = logging.getLogger("midi2osc")


def list_midi_devices() -> None:
    """Print all available MIDI input ports."""
    try:
        inputs = mido.get_input_names()  # type: ignore[attr-defined]
        print(f"{Fore.CYAN}Available MIDI Input Devices:{Style.RESET_ALL}")
        if not inputs:
            print("  (No MIDI input devices found)")
            return
        for name in inputs:
            print(f"  - {name}")
    except Exception as exc:
        print(f"{Fore.RED}✖ Error querying MIDI devices: {exc}{Style.RESET_ALL}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MIDI to OSC Converter CLI")
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
    parser.add_argument(
        "--midi-port",
        help="Override midi_port from the config file",
    )
    parser.add_argument(
        "--ip",
        help="Override OSC destination IP",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Override OSC destination UDP port",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only log warnings and errors",
    )
    parser.add_argument(
        "--no-reconnect",
        action="store_true",
        help="Exit instead of retrying when the MIDI device disconnects",
    )

    args = parser.parse_args(argv)

    if args.list_devices:
        list_midi_devices()
        sys.exit(0)

    if args.example_config:
        print(EXAMPLE_CONFIG.strip())
        sys.exit(0)

    if args.generate_config:
        out_path = Path("default.mapping.txt")
        if out_path.exists():
            print(
                f"{Fore.RED}✖ Error: 'default.mapping.txt' already exists "
                f"in this directory.{Style.RESET_ALL}"
            )
            sys.exit(1)
        out_path.write_text(EXAMPLE_CONFIG.strip() + "\n", encoding="utf-8")
        print(f"{Fore.GREEN}✔ Created 'default.mapping.txt' successfully!{Style.RESET_ALL}")
        sys.exit(0)

    if args.config:
        config_path = args.config
        if not config_path.exists():
            print(
                f"{Fore.RED}✖ Error: Config file '{config_path}' not found.{Style.RESET_ALL}"
            )
            sys.exit(1)
    else:
        default_file = Path("default.mapping.txt")
        if default_file.exists():
            config_path = default_file
        else:
            print(
                f"{Fore.RED}✖ Error: No config file specified and "
                f"'default.mapping.txt' was not found.{Style.RESET_ALL}"
            )
            print("Usage: midi2osc -c <path/to/mapping.txt>")
            print("       midi2osc -d / --list-devices")
            print("       midi2osc --generate-config")
            sys.exit(1)

    setup_logging(level=logging.WARNING if args.quiet else logging.INFO, color=True)

    try:
        config = parse_config(config_path)
        config = config.with_overrides(
            ip=args.ip,
            port=args.port,
            midi_port=args.midi_port,
        )

        logger.info("Active config: %s", config_path.name)
        logger.info("Listening on MIDI: '%s'", config.midi_port)
        logger.info("Waiting for incoming MIDI events (Press Ctrl+C to exit)...")

        run_from_config(config, reconnect=not args.no_reconnect)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Stopping MIDI to OSC Converter. Goodbye!{Style.RESET_ALL}")
        sys.exit(0)
    except MidiPortError as exc:
        logger.error("✖ %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("✖ Error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

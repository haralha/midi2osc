"""CLI entrypoint for MIDI to OSC Converter."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

import mido
import typer
from rich import print

from midi2osc.config import EXAMPLE_CONFIG, parse_config
from midi2osc.converter import MidiPortError, run_from_config
from midi2osc.logging_utils import setup_logging

logger = logging.getLogger("midi2osc")

app = typer.Typer(
    help="MIDI to OSC Converter CLI",
    add_completion=False,
    no_args_is_help=True,
)


@app.command(name="list")
def list_devices() -> None:
    """List all available MIDI input ports."""
    try:
        inputs = mido.get_input_names()  # type: ignore[attr-defined]
        print("[cyan]Available MIDI Input Devices:[/cyan]")
        if not inputs:
            print("  (No MIDI input devices found)")
            return
        for name in inputs:
            print(f"  - {name}")
    except Exception as exc:
        print(f"[bold red]✖ Error querying MIDI devices: {exc}[/bold red]")
        raise typer.Exit(code=1)


@app.command()
def generate(
    output: Path = typer.Option(
        Path("default.mapping.txt"),
        "-o",
        "--out",
        help="Path for the new configuration template",
    ),
) -> None:
    """Create a new mapping configuration template."""
    if output.exists():
        print(f"[bold red]✖ Error: '{output}' already exists.[/bold red]")
        raise typer.Exit(code=1)

    output.write_text(EXAMPLE_CONFIG.strip() + "\n", encoding="utf-8")
    print(f"[bold green]✔ Created '{output}' successfully![/bold green]")


@app.command()
def example() -> None:
    """Print an example mapping configuration to stdout."""
    print(EXAMPLE_CONFIG.strip())


@app.command()
def run(
    config_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to the mapping configuration file (*.mapping.txt)",
    ),
    ip: Optional[str] = typer.Option(None, help="Override OSC destination IP"),
    port: Optional[int] = typer.Option(None, help="Override OSC destination UDP port"),
    midi_port: Optional[str] = typer.Option(
        None, "--midi-port", help="Override MIDI port name"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Only log warnings and errors"
    ),
    mute: bool = typer.Option(
        False,
        "--mute",
        help="Log OSC messages but do not send them (safe local testing)",
    ),
    no_reconnect: bool = typer.Option(
        False,
        "--no-reconnect",
        help="Exit on disconnect instead of retrying",
    ),
) -> None:
    """Run MIDI to OSC conversion with the given configuration file."""
    setup_logging(level=logging.WARNING if quiet else logging.INFO, color=True)

    mute_event = threading.Event()
    if mute:
        mute_event.set()
        # Warning level so the notice survives --quiet.
        logger.warning(
            "OSC output is MUTED (--mute): messages are logged but not sent"
        )

    try:
        config = parse_config(config_path).with_overrides(
            ip=ip,
            port=port,
            midi_port=midi_port,
        )

        logger.info("Active config: %s", config_path.name)
        logger.info("Listening on MIDI: '%s'", config.midi_port)
        logger.info("Waiting for incoming MIDI events (Press Ctrl+C to exit)...")

        run_from_config(config, reconnect=not no_reconnect, mute_event=mute_event)
    except KeyboardInterrupt:
        print("\n[bold yellow]Stopping MIDI to OSC Converter. Goodbye![/bold yellow]")
        raise typer.Exit(code=0)
    except MidiPortError as exc:
        logger.error("✖ %s", exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.error("✖ Error: %s", exc)
        raise typer.Exit(code=1)


def main(argv: list[str] | None = None) -> None:
    """Entry point for console scripts and PyInstaller."""
    app(args=argv, prog_name="midi2osc")


if __name__ == "__main__":
    main()

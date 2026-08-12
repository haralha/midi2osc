"""Main entrypoint for the MIDI to OSC Converter CLI."""

import sys
import mido
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from config import select_config_file, parse_config
from converter import run_converter

# Tvinger konsollen til å bruke standard bakgrunnsfarger
console = Console()


def main():
    # 0. Clear terminal for a fresh view
    console.clear()

    # 1. Display modern startup banner with forced dark background
    console.print(
        Panel.fit(
            "[bold bright_cyan]🎛️  MIDI TO OSC CONVERTER[/bold bright_cyan]\n"
            "[bright_white]High-Performance Bridge for Live Performance & Stage Automation[/bright_white]",
            border_style="magenta",
            style="white on black",
            padding=(1, 4),
            subtitle="[dim white]Press Ctrl+C to stop[/dim white]",
        )
    )
    console.print()

    # 2. Select and parse configuration file
    selected_file = select_config_file()
    console.print(
        f"[bold bright_green]✔ Active config:[/bold bright_green] "
        f"[bold bright_white]{selected_file.name}[/bold bright_white]\n"
    )

    config = parse_config(selected_file)
    osc_ip = config["ip"]
    osc_port = config["port"]
    mappings = config["mappings"]

    # 3. Fetch and select MIDI port
    input_names = mido.get_input_names()  # pylint: disable=no-member
    if not input_names:
        console.print("[bold bright_red]✖ Error:[/bold bright_red] No MIDI input ports found!")
        sys.exit(1)

    port_name = config["midi_port"]
    if not port_name or port_name not in input_names:
        table = Table(
            title="[bold bright_yellow]Available MIDI Input Ports[/bold bright_yellow]",
            show_header=True,
            header_style="bold bright_cyan",
            border_style="bright_black",
            style="white on black",
        )
        table.add_column("Index", style="bold bright_green", justify="center", width=8)
        table.add_column("Port Name", style="bold bright_white")

        for i, name in enumerate(input_names):
            table.add_row(str(i), name)

        console.print(table)

        choice = Prompt.ask("\n[bold bright_cyan]Select port index[/bold bright_cyan]", default="0")
        port_index = int(choice) if choice.isdigit() and int(choice) < len(input_names) else 0
        port_name = input_names[port_index]

    # 4. Status panel before starting loop
    console.print()
    console.print(
        Panel(
            f"[bold bright_green]Listening on MIDI:[/bold bright_green] [bright_white]'{port_name}'[/bright_white]\n"
            f"[bold bright_green]Target OSC Address:[/bold bright_green] [bright_white]{osc_ip}:{osc_port}[/bright_white]\n"
            f"[bold bright_green]Custom Mappings Loaded:[/bold bright_green] [bright_white]{len(mappings)}[/bright_white]",
            title="[bold bright_cyan]System Status[/bold bright_cyan]",
            border_style="bright_cyan",
            style="white on black",
            expand=False,
        )
    )
    console.print("\n[dim white]Waiting for incoming MIDI events...[/dim white]\n")

    # 5. Start conversion loop
    try:
        run_converter(port_name, osc_ip, osc_port, mappings)
    except KeyboardInterrupt:
        console.print("\n[bold bright_yellow]👋 Exited by user.[/bold bright_yellow]\n")


if __name__ == "__main__":
    main()
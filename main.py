"""Main entrypoint for the MIDI to OSC Converter CLI."""

import sys
import mido
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import select_config_file, parse_config
from converter import run_converter

console = Console()


def main():
    console.print(
        Panel.fit(
            "[bold cyan]MIDI to OSC Converter[/bold cyan]\n"
            "[dim]Press Ctrl+C to exit[/dim]",
            border_style="cyan",
        )
    )

    # 1. Select and parse configuration file
    selected_file = select_config_file()
    console.print(f"\n[bold green]Active config:[/bold green] {selected_file.name}")

    config = parse_config(selected_file)
    osc_ip = config["ip"]
    osc_port = config["port"]
    mappings = config["mappings"]

    # 2. Fetch and select MIDI input port
    input_names = mido.get_input_names()  # pylint: disable=no-member
    if not input_names:
        console.print("[bold red]Error:[/bold red] No MIDI input ports found!")
        sys.exit(1)

    port_name = config["midi_port"]
    if not port_name or port_name not in input_names:
        table = Table(title="Available MIDI Ports", show_header=True, header_style="bold magenta")
        table.add_column("Index", style="dim", width=6)
        table.add_column("Port Name", style="bold")

        for i, name in enumerate(input_names):
            table.add_row(str(i), name)

        console.print(table)
        choice = input("\nSelect port index [default 0]: ").strip()
        port_index = int(choice) if choice.isdigit() and int(choice) < len(input_names) else 0
        port_name = input_names[port_index]

    console.print(
        f"\n[bold green]Listening on:[/bold green] '{port_name}' "
        f"-> [bold green]OSC Target:[/bold green] {osc_ip}:{osc_port}"
    )
    console.print(f"[dim]Loaded {len(mappings)} custom mappings from {selected_file.name}[/dim]\n")

    # 3. Start conversion loop
    try:
        run_converter(port_name, osc_ip, osc_port, mappings)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Exited by user.[/bold yellow]")


if __name__ == "__main__":
    main()
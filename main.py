"""Main entrypoint for the MIDI to OSC Converter CLI."""

import sys
import mido
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from config import select_config_file, parse_config
from converter import run_converter

console = Console()


def main():
    # 0. Clear terminal for a fresh view
    console.clear()

    # 1. Display modern startup banner (Tilpasset universelle farger)
    console.print(
        Panel.fit(
            "[bold magenta]🎛️  MIDI TO OSC CONVERTER[/bold magenta]\n"
            "[blue]High-Performance Bridge for Live Performance & Stage Automation[/blue]",
            border_style="magenta",
            padding=(1, 4),
            subtitle="[blue]Press Ctrl+C to stop[/blue]",
        )
    )
    console.print()

    # 2. Select and parse configuration file
    selected_file = select_config_file()
    console.print(
        f"[bold green]✔ Active config:[/bold green] "
        f"[bold]{selected_file.name}[/bold]\n"
    )

    config = parse_config(selected_file)
    osc_ip = config["ip"]
    osc_port = config["port"]
    mappings = config["mappings"]

    # 3. Fetch and select MIDI port
    input_names = mido.get_input_names()  # pylint: disable=no-member
    if not input_names:
        console.print("[bold red]✖ Error:[/bold red] No MIDI input ports found!")
        sys.exit(1)

    port_name = config["midi_port"]
    if not port_name or port_name not in input_names:
        table = Table(
            title="[bold magenta]Available MIDI Input Ports[/bold magenta]",
            show_header=True,
            header_style="bold blue",
            border_style="magenta",
        )
        table.add_column("Index", style="bold green", justify="center", width=8)
        table.add_column("Port Name", style="bold")

        for i, name in enumerate(input_names):
            table.add_row(str(i), name)

        console.print(table)

        choice = Prompt.ask("\n[bold blue]Select port index[/bold blue]", default="0")
        port_index = int(choice) if choice.isdigit() and int(choice) < len(input_names) else 0
        port_name = input_names[port_index]

    # 4. Status panel before starting loop
    console.print()
    console.print(
        Panel(
            f"[bold green]Listening on MIDI:[/bold green] [bold]'{port_name}'[/bold]\n"
            f"[bold green]Target OSC Address:[/bold green] [bold]{osc_ip}:{osc_port}[/bold]\n"
            f"[bold green]Custom Mappings Loaded:[/bold green] [bold]{len(mappings)}[/bold]",
            title="[bold magenta]System Status[/bold magenta]",
            border_style="magenta",
            expand=False,
        )
    )
    console.print("\n[blue]Waiting for incoming MIDI events...[/blue]\n")

    # 5. Start conversion loop
    try:
        run_converter(port_name, osc_ip, osc_port, mappings)
    except KeyboardInterrupt:
        console.print("\n[bold magenta]👋 Exited by user.[/bold magenta]\n")


if __name__ == "__main__":
    main()
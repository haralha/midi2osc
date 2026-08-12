"""MIDI listening and OSC routing logic."""

import mido
from pythonosc import udp_client
from rich.console import Console

console = Console()


def run_converter(port_name: str, osc_ip: str, osc_port: int, mappings: dict):
    """Main loop listening on MIDI port and dispatching OSC messages."""
    client = udp_client.SimpleUDPClient(osc_ip, osc_port)

    with mido.open_input(port_name) as inport:  # pylint: disable=no-member
        for msg in inport:
            if msg.type not in ("note_on", "note_off", "control_change"):
                continue

            num = msg.note if msg.type in ("note_on", "note_off") else msg.control
            lookup_type = "note_on" if msg.type in ("note_on", "note_off") else "control_change"
            key = (lookup_type, msg.channel, num)

            # 1. Custom mapped rule match
            if key in mappings:
                osc_addr = mappings[key]
                if msg.type == "note_on":
                    client.send_message(osc_addr, [msg.velocity])
                    console.print(f"[bold green]MAPPED ->[/bold green] {osc_addr} [dim][{msg.velocity}][/dim]")
                elif msg.type == "note_off":
                    client.send_message(osc_addr, [0])
                    console.print(f"[bold green]MAPPED ->[/bold green] {osc_addr} [dim][0][/dim]")
                elif msg.type == "control_change":
                    client.send_message(osc_addr, msg.value)
                    console.print(f"[bold green]MAPPED ->[/bold green] {osc_addr} [dim][{msg.value}][/dim]")

            # 2. Fallback unmapped routing
            else:
                if msg.type == "note_on":
                    addr = f"/midi/channel/{msg.channel}/note_on"
                    client.send_message(addr, [msg.note, msg.velocity])
                elif msg.type == "note_off":
                    addr = f"/midi/channel/{msg.channel}/note_off"
                    client.send_message(addr, [msg.note, 0])
                elif msg.type == "control_change":
                    addr = f"/midi/channel/{msg.channel}/cc/{msg.control}"
                    client.send_message(addr, msg.value)

                console.print(f"[dim]DEFAULT -> {addr}[/dim]")
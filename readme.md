# MIDI to OSC Converter

A lightweight CLI tool that converts incoming MIDI messages (`Note On/Off`, `Control Change`) into OSC packets over UDP.

Designed for live performances, stage automation, and media software such as Resolume, QLab, TouchDesigner, and Ableton Live.

## Features

- Human-readable `*.mapping.txt` configs for MIDI note and CC routing
- Multi-profile support — pick a preset (e.g. `resolume.mapping.txt`, `qlab.mapping.txt`) at launch
- Native integer OSC arguments for velocity and CC values (`0–127`)
- Fallback routing for unmapped messages (e.g. `/midi/channel/0/note_on`)
- Standalone binary build via PyInstaller into `bin/`

## Project Structure

```text
midi2osc/
  main.py               - CLI entrypoint
  config.py             - Mapping file discovery and parsing
  converter.py          - MIDI listen / OSC dispatch loop
  pyproject.toml        - Dependencies and Poe build tasks
  default.mapping.txt   - Default configuration preset
  midi2osc.spec         - PyInstaller spec (regenerated on build)
```

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/)

## Quickstart

```bash
git clone https://github.com/your-username/midi2osc.git
cd midi2osc
poetry install
poetry run python main.py
```

## Configuration (`*.mapping.txt`)

Any `*.mapping.txt` file next to the app (or binary) is treated as a preset. If none exist at startup, `default.mapping.txt` is created automatically. A legacy `mapping.txt` is also recognized.

### Example

```text
# --- NETWORK SETTINGS ---
IP: 192.168.86.36
PORT: 7700
MIDI_PORT: IAC Driver Bus 1

# --- MAPPINGS ---
# Syntax: <type> <channel 0-15> <number 0-127> -> <OSC-path>

note 0 60 -> /resolume/layer1/clip1/connect
note 0 61 -> /qlab/cue/1/start
cc 0 7    -> /composition/master/volume
```

### Directives

| Directive   | Description |
|-------------|-------------|
| `IP`        | Target OSC IP (default: `127.0.0.1`) |
| `PORT`      | Target OSC UDP port (default: `7700`) |
| `MIDI_PORT` | Exact MIDI input device name. If empty or missing, an interactive menu is shown at startup |
| Mappings    | `note` or `cc`, then channel, note/CC number, `->`, and the OSC address |

## Building the Executable

Uses [poethepoet](https://github.com/nat-n/poethepoet) and PyInstaller. Tasks are defined in `pyproject.toml`:

```toml
[tool.poe.tasks]
clean = "rm -rf build bin *.spec"
build-app = "pyinstaller --onefile --distpath bin --name midi2osc --hidden-import mido.backends.rtmidi main.py"
build = ["clean", "build-app"]
```

```bash
poetry run poe build
```

This cleans old artifacts and writes a standalone binary to `bin/midi2osc`.

## License

Distributed under the MIT License. See `LICENSE` for details.

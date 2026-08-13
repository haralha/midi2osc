# MIDI to OSC Converter

A lightweight GUI and CLI application that converts incoming MIDI messages (`Note On/Off`, `Control Change`, `Program Change`, SysEx) into OSC packets over UDP.

Designed for live performances, stage automation, and media software such as Resolume, QLab, TouchDesigner, and Ableton Live.

## Features

- Human-readable `*.mapping.txt` configs for MIDI note, CC, and program routing
- Multi-profile support — pick a preset (e.g. `resolume.mapping.txt`, `qlab.mapping.txt`) at launch
- Native integer OSC arguments for velocity and CC values (`0–127`)
- Fallback routing for unmapped messages (e.g. `/midi/channel/0/note_on`)
- Automatic reconnect when a MIDI device drops
- GUI built with PySide6 for easy control, alongside a headless CLI tool

## Prerequisites

- **Python 3.11** (3.12+ is not supported; the GUI is pinned to PySide6 6.4 for older macOS)
- **pipx** (recommended for standalone installation) or **Poetry** (for local development)

---

## Installation via `pipx` (Recommended)

`pipx` installs the application into an isolated environment and exposes the commands globally.

### 1. Install `pipx`

**On macOS (via Homebrew):**
```bash
brew install pipx
pipx ensurepath
```

**On macOS / Linux / Windows (via Python):**
```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```
(Restart your terminal after running `ensurepath`.)

### 2. Install midi2osc

From GitHub:
```bash
pipx install git+https://github.com/haralha/midi2osc.git
```

Or from a local clone:
```bash
git clone https://github.com/haralha/midi2osc.git
cd midi2osc
pipx install .
```

### 3. Usage via pipx

```bash
midi2osc-gui          # GUI
midi2osc              # CLI
midi2osc -d           # list MIDI devices
pipx upgrade midi2osc # update later
```

## Development & Local Execution

```bash
git clone https://github.com/haralha/midi2osc.git
cd midi2osc
poetry install
```

```bash
poetry run poe gui
poetry run poe cli
poetry run poe test
```

## Configuration (`*.mapping.txt`)

Use a `*.mapping.txt` file. Generate a starter template with:

```bash
midi2osc --generate-config
```

### Example

```
# Channels are 0-15 (MIDI channel 1 = 0 in this file).
# Notes/CC numbers are 0-127.

midi_port = "IAC Driver Bus 1"
ip = "127.0.0.1"
port = 8000
convert_unmapped = true

# note / note_on maps both note-on and note-off (incl. note_on velocity 0)
note 0 60 -> /resolume/layer1/clip1/connect
note 0 61 -> /qlab/cue/1/start
cc 0 7 -> /composition/master/volume
pc 0 1 -> /qlab/cue/2/start
```

### Settings

| Key | Description |
|-----|-------------|
| `midi_port` | MIDI input device name (exact preferred; unique substring also works) |
| `ip` / `host` | Target OSC IP (default `127.0.0.1`) |
| `port` / `osc_port` | Target OSC UDP port (default `7700`) |
| `convert_unmapped` | If `true`, unmapped messages are sent to `/midi/...` defaults; if `false`, they are only logged |

### Mapping syntax

```
<event> <channel 0-15> <number 0-127> -> /osc/address
sysex -> /midi/sysex
```

Event aliases: `note` / `note_on`, `cc` / `control`, `pc` / `program`.

**Note semantics:** `note_on` with velocity `0` is treated as note-off (MIDI convention). A single `note` mapping covers both on and off; the OSC value is the velocity (`0` for off).

### CLI overrides

```bash
midi2osc -c show.mapping.txt --midi-port "IAC Driver Bus 1" --ip 192.168.1.10 --port 7700
midi2osc -c show.mapping.txt --quiet
midi2osc -c show.mapping.txt --no-reconnect
```

## Building Executables

```bash
poetry run poe build        # Windows / Linux
poetry run poe build-mac    # macOS
```

Binaries are written to `bin/`.

## License

Distributed under the MIT License. See LICENSE for details.

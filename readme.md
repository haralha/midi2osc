# MIDI to OSC Converter

A lightweight GUI and CLI application that converts incoming MIDI messages (`Note On/Off`, `Control Change`) into OSC packets over UDP.

Designed for live performances, stage automation, and media software such as Resolume, QLab, TouchDesigner, and Ableton Live.

## Features

- Human-readable `*.mapping.txt` configs for MIDI note and CC routing
- Multi-profile support — pick a preset (e.g. `resolume.mapping.txt`, `qlab.mapping.txt`) at launch
- Native integer OSC arguments for velocity and CC values (`0–127`)
- Fallback routing for unmapped messages (e.g. `/midi/channel/0/note_on`)
- GUI built with PySide6 for easy control, alongside a headless CLI tool

## Prerequisites

- **Python 3.12+**
- **pipx** (Recommended for standalone installation) or **Poetry** (for local development)

---

## Installation via `pipx` (Recommended)

`pipx` installs the application into an isolated environment and exposes the commands globally without interfering with your system's Python setup. This is ideal for older systems or stage computers where you want a reliable, hassle-free installation.

### 1. Install `pipx`
If you haven't installed `pipx` yet, make sure Python 3.12+ is installed, then run:

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
(Restart your terminal after running ensurepath)

1. Install midi2osc

Directly from GitHub:
```bash
pipx install git+[https://github.com/your-username/midi2osc.git](https://github.com/your-username/midi2osc.git)
```

Or from a local clone:
```bash
git clone [https://github.com/your-username/midi2osc.git](https://github.com/your-username/midi2osc.git)
cd midi2osc
pipx install .
```

1. Usage via pipx

Once installed, you can launch the app directly from any terminal window:

Launch GUI:
```bash
midi2osc-gui
```

Launch CLI:
```bash
midi2osc
```

To update to the latest version in the future:
```bash
pipx upgrade midi2osc
```

Development & Local Execution
If you want to modify the source code or develop locally using Poetry:
```bash
git clone [https://github.com/your-username/midi2osc.git](https://github.com/your-username/midi2osc.git)
cd midi2osc
poetry install
```

Run GUI:
```bash
poetry run poe gui
```

Run CLI:
```bash
poetry run poe cli
```

Configuration (*.mapping.txt)
Any *.mapping.txt file next to the app is treated as a preset. If none exist at startup, default.mapping.txt is created automatically. A legacy mapping.txt is also recognized.

Example
```
--- NETWORK SETTINGS ---
IP: 127.0.0.1
PORT: 7700
MIDI_PORT: IAC Driver Bus 1

--- MAPPINGS ---
Syntax:  <channel 0-15> <number 0-127> ->

note 0 60 -> /resolume/layer1/clip1/connect
note 0 61 -> /qlab/cue/1/start
cc 0 7 -> /composition/master/volume
```

Directives
IP: Target OSC IP (default: 127.0.0.1)
PORT: Target OSC UDP port (default: 7700)
MIDI_PORT: Exact MIDI input device name. If empty or missing, an interactive menu is shown at startup
Mappings: note or cc, then channel, note/CC number, ->, and the OSC address

Building Executables (Standalone Packaging)
Standalone binaries can be compiled locally or via GitHub Actions using PyInstaller and poethepoet:

```bash
poetry run poe build
```

The compiled binaries will be output to the bin/ directory.

License
Distributed under the MIT License. See LICENSE for details.
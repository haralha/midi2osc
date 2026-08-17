"""Shared logging helpers for CLI and GUI."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Optional

from colorama import Fore, Style, init as colorama_init

if TYPE_CHECKING:
    from midi2osc.converter import RoutedMessage

LOG_FORMAT = "%(message)s"

# Style keys produced by build_routed_tokens(); CLI and GUI map these independently.
STYLE_MIDI_IN = "midi_in"
STYLE_MAPPED = "mapped"
STYLE_UNMAPPED = "unmapped"
STYLE_DEFAULT_STATUS = "default_status"
STYLE_DEFAULT = "default"
STYLE_MUTED = "muted"

_STATUS_KEYWORDS = (
    "Listening on MIDI",
    "Target OSC",
    "Active config",
    "Convert unmapped",
    "Mappings loaded",
    "OSC output",
)

_ROUTED_STYLE_MAP = {
    STYLE_MIDI_IN: f"{Fore.GREEN}{Style.BRIGHT}",
    STYLE_MAPPED: f"{Fore.GREEN}{Style.BRIGHT}",
    STYLE_UNMAPPED: Fore.WHITE,
    STYLE_DEFAULT_STATUS: Fore.YELLOW,
    STYLE_DEFAULT: Style.RESET_ALL,
    STYLE_MUTED: f"{Fore.MAGENTA}{Style.BRIGHT}",
}


def _format_value(value: object) -> str:
    """Format an OSC payload for log output."""
    if isinstance(value, (list, tuple)):
        return " ".join(map(str, value))
    return str(value)


def build_routed_tokens(routed: RoutedMessage) -> list[tuple[str, str]]:
    """Build shared MIDI log layout as (style_key, text) tokens.

    Layout matches the historical CLI/GUI lines:

    ``MIDI IN: {midi_sig:<16} ➔ MAPPED  -> {addr} [{val}]``
    ``MIDI IN: {midi_sig:<16} ➔ DEFAULT -> {addr} [{val}]``
    ``MIDI IN: {midi_sig:<16} ➔ UNMAPPED (LOGGED ONLY) [{val}]``

    Sendable lines get a trailing ``(MUTED)`` marker while output is muted.
    """
    val_str = _format_value(routed.value)
    tokens: list[tuple[str, str]] = [
        (STYLE_MIDI_IN, "MIDI IN:"),
        (STYLE_DEFAULT, f" {routed.midi_sig:<16} ➔ "),
    ]
    if routed.mapped:
        tokens.append((STYLE_MAPPED, "MAPPED"))
        tokens.append((STYLE_DEFAULT, f"  -> {routed.osc_address} [{val_str}]"))
    elif routed.send:
        tokens.append((STYLE_DEFAULT_STATUS, "DEFAULT"))
        tokens.append((STYLE_DEFAULT, f" -> {routed.osc_address} [{val_str}]"))
    else:
        tokens.append((STYLE_UNMAPPED, "UNMAPPED"))
        tokens.append((STYLE_DEFAULT, f" (LOGGED ONLY) [{val_str}]"))

    if routed.send and routed.muted:
        tokens.append((STYLE_MUTED, " (MUTED)"))
    return tokens


class ColorFormatter(logging.Formatter):
    """Colorize midi2osc log lines for terminal output."""

    def format(self, record: logging.LogRecord) -> str:
        routed = getattr(record, "routed_msg", None)
        if routed is not None:
            colored_parts = []
            for style_key, text in build_routed_tokens(routed):
                color = _ROUTED_STYLE_MAP.get(style_key, "")
                colored_parts.append(f"{color}{text}{Style.RESET_ALL}")
            return "".join(colored_parts)

        text = super().format(record)

        # Safety net for MIDI lines logged without routed_msg extra.
        if "MIDI IN:" in text:
            text = text.replace(
                "MIDI IN:", f"{Fore.GREEN}{Style.BRIGHT}MIDI IN:{Style.RESET_ALL}"
            )
        if "UNMAPPED" in text:
            text = text.replace("UNMAPPED", f"{Fore.WHITE}UNMAPPED{Style.RESET_ALL}")
        elif "MAPPED" in text:
            text = text.replace(
                "MAPPED", f"{Fore.GREEN}{Style.BRIGHT}MAPPED{Style.RESET_ALL}"
            )
        if "DEFAULT" in text:
            text = text.replace("DEFAULT", f"{Fore.YELLOW}DEFAULT{Style.RESET_ALL}")

        if record.levelno >= logging.ERROR:
            return f"{Fore.RED}{Style.BRIGHT}{text}{Style.RESET_ALL}"
        if record.levelno >= logging.WARNING:
            return f"{Fore.YELLOW}{text}{Style.RESET_ALL}"
        if any(k in text for k in _STATUS_KEYWORDS):
            return f"{Fore.CYAN}{text}{Style.RESET_ALL}"
        return text


def setup_logging(
    *,
    level: int = logging.INFO,
    color: bool = True,
    handler: Optional[logging.Handler] = None,
) -> logging.Logger:
    """Configure the midi2osc logger once for process entrypoints."""
    logger = logging.getLogger("midi2osc")
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        if color:
            colorama_init(autoreset=True)
            handler.setFormatter(ColorFormatter(LOG_FORMAT))
        else:
            handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger.addHandler(handler)
    return logger

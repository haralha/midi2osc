"""Shared logging helpers for CLI and GUI."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from colorama import Fore, Style, init as colorama_init

LOG_FORMAT = "%(message)s"


class ColorFormatter(logging.Formatter):
    """Colorize midi2osc log lines for terminal output."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)

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
        if any(
            k in text
            for k in ("Listening on MIDI", "Target OSC", "Active config", "Convert unmapped", "Mappings loaded")
        ):
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

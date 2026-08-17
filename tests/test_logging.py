"""Unit tests for shared routed-log tokens and ColorFormatter."""

from __future__ import annotations

import logging

from colorama import Fore, Style

from midi2osc.converter import RoutedMessage
from midi2osc.logging_utils import (
    STYLE_DEFAULT,
    STYLE_DEFAULT_STATUS,
    STYLE_MAPPED,
    STYLE_MIDI_IN,
    STYLE_UNMAPPED,
    ColorFormatter,
    build_routed_tokens,
)


def _join_tokens(routed: RoutedMessage) -> str:
    return "".join(text for _, text in build_routed_tokens(routed))


def _record_with_routed(routed: RoutedMessage) -> logging.LogRecord:
    record = logging.LogRecord(
        name="midi2osc",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="unused",
        args=(),
        exc_info=None,
    )
    record.routed_msg = routed  # type: ignore[attr-defined]
    return record


def test_mapped_tokens_match_historical_layout() -> None:
    routed = RoutedMessage(
        midi_sig="note 1 60",
        osc_address="/clip/start",
        value=100,
        mapped=True,
        send=True,
    )
    tokens = build_routed_tokens(routed)
    assert tokens[0] == (STYLE_MIDI_IN, "MIDI IN:")
    assert (STYLE_MAPPED, "MAPPED") in tokens
    assert _join_tokens(routed) == "MIDI IN: note 1 60    ➔ MAPPED  -> /clip/start [100]"


def test_default_tokens_match_historical_layout() -> None:
    routed = RoutedMessage(
        midi_sig="cc 1 7",
        osc_address="/midi/channel/1/cc/7",
        value=64,
        mapped=False,
        send=True,
    )
    tokens = build_routed_tokens(routed)
    assert (STYLE_DEFAULT_STATUS, "DEFAULT") in tokens
    assert (STYLE_DEFAULT, " -> /midi/channel/1/cc/7 [64]") in tokens
    assert _join_tokens(routed) == (
        "MIDI IN: cc 1 7       ➔ DEFAULT -> /midi/channel/1/cc/7 [64]"
    )


def test_unmapped_tokens_match_historical_layout() -> None:
    routed = RoutedMessage(
        midi_sig="pc 2 5",
        osc_address="/midi/channel/2/program_change",
        value=5,
        mapped=False,
        send=False,
    )
    tokens = build_routed_tokens(routed)
    assert (STYLE_UNMAPPED, "UNMAPPED") in tokens
    assert _join_tokens(routed) == (
        "MIDI IN: pc 2 5       ➔ UNMAPPED (LOGGED ONLY) [5]"
    )


def test_list_value_is_space_joined() -> None:
    routed = RoutedMessage(
        midi_sig="sysex",
        osc_address="/midi/sysex",
        value=[1, 2, 3],
        mapped=False,
        send=True,
    )
    assert "[1 2 3]" in _join_tokens(routed)


def test_color_formatter_uses_routed_msg_extra() -> None:
    formatter = ColorFormatter("%(message)s")

    mapped = formatter.format(
        _record_with_routed(
            RoutedMessage("note 1 60", "/clip/start", 100, True, True)
        )
    )
    assert f"{Fore.GREEN}{Style.BRIGHT}MAPPED{Style.RESET_ALL}" in mapped
    assert "MAPPED" in mapped

    default = formatter.format(
        _record_with_routed(
            RoutedMessage("cc 1 7", "/midi/channel/1/cc/7", 10, False, True)
        )
    )
    assert f"{Fore.YELLOW}DEFAULT{Style.RESET_ALL}" in default

    unmapped = formatter.format(
        _record_with_routed(
            RoutedMessage("cc 1 7", "/midi/channel/1/cc/7", 10, False, False)
        )
    )
    assert f"{Fore.WHITE}UNMAPPED{Style.RESET_ALL}" in unmapped
    assert f"{Fore.GREEN}{Style.BRIGHT}MIDI IN:{Style.RESET_ALL}" in unmapped

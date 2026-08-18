"""Unit tests for shared routed-log tokens and ColorFormatter."""

from __future__ import annotations

import logging

from colorama import Fore, Style

from midi2osc.converter import RoutedMessage
from midi2osc.logging_utils import (
    LOG_KIND_STATUS,
    STYLE_DEFAULT,
    STYLE_DEFAULT_STATUS,
    STYLE_MAPPED,
    STYLE_MIDI_IN,
    STYLE_MUTED,
    STYLE_UNMAPPED,
    ColorFormatter,
    build_routed_tokens,
    record_routed_tokens,
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
        midi_sig="note_on 1 60",
        osc_address="/clip/start",
        value=100,
        mapped=True,
        send=True,
    )
    tokens = build_routed_tokens(routed)
    assert tokens[0] == (STYLE_MIDI_IN, "MIDI IN:")
    assert (STYLE_MAPPED, "MAPPED") in tokens
    assert _join_tokens(routed) == "MIDI IN: note_on 1 60     ➔ MAPPED  -> /clip/start [100]"


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
        "MIDI IN: cc 1 7           ➔ DEFAULT -> /midi/channel/1/cc/7 [64]"
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
        "MIDI IN: pc 2 5           ➔ UNMAPPED (LOGGED ONLY) [5]"
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


def test_muted_marker_appended_to_sendable_lines() -> None:
    mapped = RoutedMessage(
        midi_sig="cc 1 7",
        osc_address="/volume",
        value=0.5,
        mapped=True,
        send=True,
        muted=True,
    )
    tokens = build_routed_tokens(mapped)
    assert tokens[-1] == (STYLE_MUTED, " (MUTED)")
    assert (STYLE_MAPPED, "MAPPED") in tokens
    assert _join_tokens(mapped) == (
        "MIDI IN: cc 1 7           ➔ MAPPED  -> /volume [0.5] (MUTED)"
    )


def test_muted_marker_omitted_when_not_muted_or_not_sent() -> None:
    live = RoutedMessage("cc 1 7", "/volume", 0.5, True, True)
    unmapped_muted = RoutedMessage(
        "cc 1 7", "/midi/channel/1/cc/7", 10, False, False, muted=True
    )
    assert "(MUTED)" not in _join_tokens(live)
    assert "(MUTED)" not in _join_tokens(unmapped_muted)


def test_color_formatter_colors_muted_marker() -> None:
    formatter = ColorFormatter("%(message)s")
    text = formatter.format(
        _record_with_routed(
            RoutedMessage("cc 1 7", "/volume", 0.5, True, True, muted=True)
        )
    )
    assert f"{Fore.MAGENTA}{Style.BRIGHT} (MUTED){Style.RESET_ALL}" in text


def test_color_formatter_uses_routed_msg_extra() -> None:
    formatter = ColorFormatter("%(message)s")

    mapped = formatter.format(
        _record_with_routed(
            RoutedMessage("note_on 1 60", "/clip/start", 100, True, True)
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


def test_color_formatter_uses_log_kind_for_status() -> None:
    formatter = ColorFormatter("%(message)s")
    record = logging.LogRecord(
        name="midi2osc",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Listening on MIDI: 'IAC'",
        args=(),
        exc_info=None,
    )
    record.log_kind = LOG_KIND_STATUS  # type: ignore[attr-defined]
    text = formatter.format(record)
    assert f"{Fore.CYAN}Listening on MIDI: 'IAC'{Style.RESET_ALL}" == text


def test_color_formatter_does_not_substring_match_midi_tokens() -> None:
    formatter = ColorFormatter("%(message)s")
    record = logging.LogRecord(
        name="midi2osc",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="plain line mentioning MIDI IN: MAPPED DEFAULT UNMAPPED",
        args=(),
        exc_info=None,
    )
    text = formatter.format(record)
    assert text == "plain line mentioning MIDI IN: MAPPED DEFAULT UNMAPPED"


def test_record_routed_tokens_prefers_prebuilt() -> None:
    routed = RoutedMessage("cc 1 7", "/volume", 1, True, True)
    record = _record_with_routed(routed)
    prebuilt = [("custom", "prebuilt")]
    record.routed_tokens = prebuilt  # type: ignore[attr-defined]
    assert record_routed_tokens(record) == prebuilt


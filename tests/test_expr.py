"""Unit tests for safe OSC value expressions."""

import pytest

from midi2osc.expr import ExprError, evaluate_osc_value, parse_value_expr


def test_raw_math_and_casts() -> None:
    assert evaluate_osc_value("v/127", 127) == 1.0
    assert evaluate_osc_value("v/127", 0) == 0.0
    assert evaluate_osc_value("1 - (v/127)", 127) == 0.0
    assert evaluate_osc_value("1 - (v/127)", 0) == 1.0
    assert evaluate_osc_value("int(20 + v * 150)", 0) == 20
    assert evaluate_osc_value("int(20 + v * 150)", 1) == 170
    assert evaluate_osc_value("float(v)", 64) == 64.0
    assert evaluate_osc_value("int(v / 10)", 55) == 5
    assert evaluate_osc_value("1", 99) == 1


def test_string_template() -> None:
    assert evaluate_osc_value('"cue_{v}"', 3) == "cue_3"
    assert evaluate_osc_value('"hello world"', 0) == "hello world"


def test_rejects_unknown_names_and_calls() -> None:
    with pytest.raises(ExprError):
        parse_value_expr("x + 1")
    with pytest.raises(ExprError):
        parse_value_expr("__import__('os')")
    with pytest.raises(ExprError):
        parse_value_expr("abs(v)")
    with pytest.raises(ExprError):
        parse_value_expr("v.real")


def test_rejects_bad_string_templates() -> None:
    with pytest.raises(ExprError):
        parse_value_expr('"cue_{other}"')
    with pytest.raises(ExprError):
        parse_value_expr("'cue_{v}'")


def test_division_by_zero() -> None:
    with pytest.raises(ExprError, match="division by zero"):
        evaluate_osc_value("v / 0", 10)


def test_parse_roundtrip() -> None:
    tree = parse_value_expr("v / 127")
    from midi2osc.expr import eval_value_expr

    assert eval_value_expr(tree, 127) == 1.0

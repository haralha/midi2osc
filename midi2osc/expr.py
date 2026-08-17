"""Safe evaluation of optional OSC value expressions from mapping files."""

from __future__ import annotations

import ast
import operator
from typing import Callable, Union

ExprResult = Union[int, float, str]

_BIN_OPS: dict[type[ast.operator], Callable[[int | float, int | float], int | float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], Callable[[int | float], int | float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_CALLS: dict[str, Callable[[int | float], int | float]] = {
    "int": int,
    "float": float,
}


class ExprError(ValueError):
    """Raised when a value expression is invalid or cannot be evaluated."""


def _is_quoted_string(src: str) -> bool:
    return len(src) >= 2 and src[0] == '"' and src[-1] == '"'


def _format_placeholder_value(result: int | float) -> str:
    if isinstance(result, float) and result.is_integer():
        return str(int(result))
    return str(result)


def _eval_formatted_value(node: ast.FormattedValue, v: int) -> str:
    if node.conversion != -1:
        raise ExprError("string placeholders do not support !s/!r/!a conversions")
    if node.format_spec is not None:
        raise ExprError("string placeholders do not support format specs")
    _validate_node(node.value)
    result = _eval_ast(node.value, v)
    if isinstance(result, bool):
        raise ExprError("boolean results are not allowed")
    if not isinstance(result, (int, float)):
        raise ExprError(f"unexpected result type: {type(result).__name__}")
    return _format_placeholder_value(result)


def eval_string_template(src: str, v: int) -> str:
    """Evaluate a quoted string template with ``{expr}`` placeholders.

    Mapping files use ordinary double-quoted strings; internally they are
    parsed as Python f-strings so placeholders reuse the same safe AST
    expression language as numeric values.
    """
    if not _is_quoted_string(src):
        raise ExprError(f"not a quoted string: {src!r}")

    try:
        tree = ast.parse("f" + src, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"invalid string template: {exc.msg}") from exc

    body = tree.body
    if not isinstance(body, ast.JoinedStr):
        raise ExprError(f"unsupported string template form: {type(body).__name__}")

    parts: list[str] = []
    for node in body.values:
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, str):
                raise ExprError(f"unsupported f-string constant: {node.value!r}")
            parts.append(node.value)
        elif isinstance(node, ast.FormattedValue):
            parts.append(_eval_formatted_value(node, v))
        else:
            raise ExprError(f"unsupported f-string node: {type(node).__name__}")
    return "".join(parts)


def _validate_node(node: ast.AST) -> None:
    """Reject AST nodes that are not part of the allowed expression subset."""
    if isinstance(node, ast.Expression):
        _validate_node(node.body)
        return

    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ExprError(f"unsupported constant: {node.value!r}")
        return

    if isinstance(node, ast.Name):
        if node.id != "v":
            raise ExprError(f"unknown name: {node.id!r}")
        return

    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN_OPS:
            raise ExprError(f"unsupported operator: {type(node.op).__name__}")
        _validate_node(node.left)
        _validate_node(node.right)
        return

    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY_OPS:
            raise ExprError(f"unsupported unary operator: {type(node.op).__name__}")
        _validate_node(node.operand)
        return

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
            raise ExprError("only int() and float() calls are allowed")
        if node.keywords or len(node.args) != 1:
            raise ExprError(f"{node.func.id}() takes exactly one positional argument")
        _validate_node(node.args[0])
        return

    raise ExprError(f"unsupported expression node: {type(node).__name__}")


def parse_value_expr(src: str) -> ast.Expression | str:
    """Parse and validate a value expression.

    Returns a quoted string (still including quotes) or an ``ast.Expression``
    ready for evaluation. Raises ``ExprError`` on invalid input.
    """
    text = src.strip()
    if not text:
        raise ExprError("empty expression")

    if _is_quoted_string(text):
        # Validate template placeholders at parse time (v=0 is fine).
        eval_string_template(text, 0)
        return text

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"invalid syntax: {exc.msg}") from exc

    _validate_node(tree)
    return tree


def _eval_ast(node: ast.AST, v: int) -> int | float:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, v)

    if isinstance(node, ast.Constant):
        value = node.value
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        return value

    if isinstance(node, ast.Name):
        if node.id != "v":
            raise ExprError(f"unknown name: {node.id!r}")
        return v

    if isinstance(node, ast.BinOp):
        bin_op = _BIN_OPS.get(type(node.op))
        if bin_op is None:
            raise ExprError(f"unsupported operator: {type(node.op).__name__}")
        left = _eval_ast(node.left, v)
        right = _eval_ast(node.right, v)
        try:
            return bin_op(left, right)
        except ZeroDivisionError as exc:
            raise ExprError("division by zero") from exc

    if isinstance(node, ast.UnaryOp):
        unary_op = _UNARY_OPS.get(type(node.op))
        if unary_op is None:
            raise ExprError(f"unsupported unary operator: {type(node.op).__name__}")
        return unary_op(_eval_ast(node.operand, v))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
            raise ExprError("only int() and float() calls are allowed")
        if node.keywords or len(node.args) != 1:
            raise ExprError(f"{node.func.id}() takes exactly one positional argument")
        fn = _ALLOWED_CALLS[node.func.id]
        return fn(_eval_ast(node.args[0], v))

    raise ExprError(f"unsupported expression node: {type(node).__name__}")


def eval_value_expr(expr: ast.Expression | str, v: int) -> ExprResult:
    """Evaluate a previously parsed expression with MIDI value ``v``."""
    if isinstance(expr, str):
        return eval_string_template(expr, v)
    result = _eval_ast(expr, v)
    if isinstance(result, bool):
        raise ExprError("boolean results are not allowed")
    if not isinstance(result, (int, float)):
        raise ExprError(f"unexpected result type: {type(result).__name__}")
    return result


def evaluate_osc_value(expr_str: str, midi_val: int) -> ExprResult:
    """Parse and evaluate an expression string in one step."""
    return eval_value_expr(parse_value_expr(expr_str), midi_val)

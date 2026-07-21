"""Small, non-executing evaluator for observed PContent numeric expressions."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Mapping

_VARIABLE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\$")
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _strip_outer_parentheses(value: str) -> str:
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        enclosed = True
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    enclosed = False
                    break
        if not enclosed or depth:
            break
        value = value[1:-1].strip()
    return value


def _ternary_parts(value: str) -> tuple[str, str, str] | None:
    depth = 0
    question = -1
    nested = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "?" and question < 0:
            question = index
            nested = 1
        elif character == "?" and question >= 0:
            nested += 1
        elif character == ":" and question >= 0:
            nested -= 1
            if nested == 0:
                return value[:question], value[question + 1:index], value[index + 1:]
    return None


def _evaluate_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return float(_BINARY[type(node.op)](_evaluate_node(node.left), _evaluate_node(node.right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return float(_UNARY[type(node.op)](_evaluate_node(node.operand)))
    if isinstance(node, ast.Compare) and all(
        type(operation) in _COMPARE for operation in node.ops
    ):
        values = [_evaluate_node(node.left), *map(_evaluate_node, node.comparators)]
        return float(
            all(
                _COMPARE[type(operation)](left, right)
                for operation, left, right in zip(
                    node.ops,
                    values[:-1],
                    values[1:],
                    strict=True,
                )
            )
        )
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        values = [bool(_evaluate_node(value)) for value in node.values]
        return float(all(values) if isinstance(node.op, ast.And) else any(values))
    raise ValueError("unsupported PContent expression")


def evaluate_expression(
    expression: object,
    variables: Mapping[str, float | bool] | None = None,
    *,
    default: float = 0.0,
) -> float:
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        return float(expression)
    if not isinstance(expression, str) or not expression.strip():
        return default
    values = {key.casefold(): value for key, value in (variables or {}).items()}

    def replace(match: re.Match[str]) -> str:
        value = values.get(match.group(1).casefold(), 0.0)
        return "1" if value is True else "0" if value is False else repr(float(value))

    text = _VARIABLE.sub(replace, expression.strip())
    if text.startswith("@"):
        text = text[1:].strip()
    text = _strip_outer_parentheses(text)
    ternary = _ternary_parts(text)
    try:
        if ternary is not None:
            condition, when_true, when_false = ternary
            branch = when_true if evaluate_expression(condition, default=0.0) else when_false
            return evaluate_expression(branch, default=default)
        tree = ast.parse(text, mode="eval")
        return _evaluate_node(tree)
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return default

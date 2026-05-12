"""AST-based safe expression evaluator — replaces eval() in calculator tools."""

import ast
import operator
from typing import Any

_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expression: str) -> float:
    """Evaluate a mathematical expression safely using AST parsing.

    Supports: +, -, *, /, //, %, **, parentheses, floats, and negative numbers.
    Raises ValueError for unsafe or invalid expressions.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"invalid expression: {e}") from e

    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"unsupported constant: {type(node.value).__name__}")

    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand))

    if isinstance(node, ast.BinOp):
        op = _ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported binary operator: {type(node.op).__name__}")
        return op(_eval_node(node.left), _eval_node(node.right))

    raise ValueError(f"unsupported syntax: {type(node).__name__}")

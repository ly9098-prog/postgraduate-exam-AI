"""Strict expression parser — AST-level validation before sympy.

No raw sympy.sympify() on untrusted input. Validates using Python's ``ast``
module first, with a whitelist of allowed node types and symbol names.
"""

import ast
import logging
import math

import sympy as sp

logger = logging.getLogger(__name__)

# ── Limits ──
MAX_EXPRESSION_LENGTH = 500
MAX_AST_NODES = 100
MAX_AST_DEPTH = 20
MAX_ESTIMATED_DIGITS = 1000
MAX_POWER_EXPONENT_LOG10 = 6
_MIN_LOG_SIZE = math.log10(2)

# ── Allowed AST node types ──
ALLOWED_AST_TYPES = frozenset(
    {
        ast.Expression,
        ast.Name,
        ast.Constant,
        ast.UnaryOp,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.Call,
        ast.Load,
    }
)

# ── Forbidden AST node types (explicit check) ──
FORBIDDEN_AST_TYPES = frozenset(
    {
        ast.Attribute,
        ast.Subscript,
        ast.Lambda,
        ast.List,
        ast.Dict,
        ast.Set,
        ast.Tuple,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.Starred,
        ast.Yield,
        ast.YieldFrom,
        ast.Await,
    }
)

# ── Allowed symbols for sympy ──
SAFE_SYMPY_NAMESPACE = {
    # Variable
    "x": sp.Symbol("x"),
    # Constants
    "pi": sp.pi,
    "e": sp.E,
    # Trig
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "atan2": sp.atan2,
    # Hyperbolic
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    # Exp / Log
    "exp": sp.exp,
    "log": sp.log,
    "ln": sp.log,
    # Power / Root
    "sqrt": sp.sqrt,
    # Misc
    "abs": sp.Abs,
    "sign": sp.sign,
    "floor": sp.floor,
    "ceil": sp.ceiling,
}

# ── Names allowed as AST Name nodes (variables or function calls) ──
ALLOWED_NAMES = frozenset(SAFE_SYMPY_NAMESPACE.keys())


def validate_expression(expr_str: str) -> None:
    """Validate an expression string for safe sympy evaluation.

    Raises ``ValueError`` if the expression violates any safety rule.
    """
    if not expr_str or not expr_str.strip():
        raise ValueError("Expression is empty")

    if len(expr_str) > MAX_EXPRESSION_LENGTH:
        raise ValueError(
            f"Expression too long ({len(expr_str)} chars, max {MAX_EXPRESSION_LENGTH})"
        )

    try:
        tree = ast.parse(expr_str.strip(), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Expression syntax error: {e}")

    # Count nodes and track depth
    node_count = 0

    def _walk(node, depth=0):
        nonlocal node_count
        node_count += 1

        if node_count > MAX_AST_NODES:
            raise ValueError(f"Expression too complex (>{MAX_AST_NODES} AST nodes)")

        if depth > MAX_AST_DEPTH:
            raise ValueError(f"Expression nesting too deep (>{MAX_AST_DEPTH} levels)")

        node_type = type(node)

        # Check forbidden types first
        if node_type in FORBIDDEN_AST_TYPES:
            raise ValueError(
                f"Forbidden construct: {node_type.__name__} "
                f"(attribute access, subscript, lambda, containers, etc.)"
            )

        # Check allowed types
        if node_type not in ALLOWED_AST_TYPES:
            raise ValueError(f"Unknown construct: {node_type.__name__}")

        # Type-specific checks
        if node_type == ast.Name:
            if node.id.startswith("_"):
                raise ValueError(f"Invalid identifier: '{node.id}'")
            if node.id not in ALLOWED_NAMES:
                raise ValueError(
                    f"Unknown symbol: '{node.id}'. "
                    f"Allowed: {', '.join(sorted(ALLOWED_NAMES))}"
                )

        elif node_type == ast.Constant:
            if isinstance(node.value, str):
                raise ValueError("String literals are not allowed")
            if isinstance(node.value, (complex, bytes)):
                raise ValueError(
                    f"Unsupported constant type: {type(node.value).__name__}"
                )
            if isinstance(node.value, float) and (node.value != node.value):
                raise ValueError("NaN is not allowed in expressions")

        elif node_type == ast.Call:
            # Function name must be ast.Name (not attribute access)
            func = node.func
            if not isinstance(func, ast.Name):
                raise ValueError(
                    "Only simple function calls are allowed (no method calls)"
                )
            if func.id not in ALLOWED_NAMES:
                raise ValueError(
                    f"Unknown function: '{func.id}'. "
                    f"Allowed: {', '.join(sorted(ALLOWED_NAMES))}"
                )
            # Recursively validate arguments
            for arg in node.args:
                _walk(arg, depth + 1)

        # Recurse into child nodes
        for child in ast.iter_child_nodes(node):
            _walk(child, depth + 1)

    _walk(tree)
    _estimate_log_size(tree.body)


def _estimate_log_size(node) -> float:
    """Upper-bound log10 size of a subtree's exact value (x counts as 1).

    sympify evaluates integer and rational powers eagerly, so a short input such
    as ``9**9**9**9`` would otherwise hang the process.
    """
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            return _MIN_LOG_SIZE
        value = abs(node.value)
        if value == 0 or value == float("inf"):
            return _MIN_LOG_SIZE
        if isinstance(node.value, int):
            return max(len(str(value)), _MIN_LOG_SIZE)
        return max(abs(math.log10(value)), _MIN_LOG_SIZE)
    if isinstance(node, ast.Name):
        return _MIN_LOG_SIZE
    if isinstance(node, ast.UnaryOp):
        return _estimate_log_size(node.operand)
    if isinstance(node, ast.Call):
        return max((_estimate_log_size(arg) for arg in node.args), default=_MIN_LOG_SIZE)
    if isinstance(node, ast.BinOp):
        left = _estimate_log_size(node.left)
        right = _estimate_log_size(node.right)
        if isinstance(node.op, ast.Pow):
            if right > MAX_POWER_EXPONENT_LOG10:
                raise ValueError("Exponent too large")
            size = left * 10**right
        else:
            size = left + right
        if size > MAX_ESTIMATED_DIGITS:
            raise ValueError("Expression value too large to evaluate safely")
        return size
    return _MIN_LOG_SIZE


def parse_expression(expr_str: str) -> sp.Expr:
    """Validate and parse an expression string into a sympy expression.

    Returns a sympy ``Expr`` ready for ``lambdify``.

    Raises ``ValueError`` if the expression is invalid or unsafe.
    """
    validate_expression(expr_str)

    try:
        expr = sp.sympify(expr_str, locals=SAFE_SYMPY_NAMESPACE)
    except (sp.SympifyError, TypeError, ValueError) as e:
        raise ValueError(f"Cannot parse expression '{expr_str}': {e}")

    if not isinstance(expr, sp.Expr):
        raise ValueError(
            f"Expression '{expr_str}' did not produce a valid symbolic expression"
        )

    return expr


def lambdify_expression(expr: sp.Expr):
    """Convert a sympy expression to a numpy-compatible callable.

    Returns a function ``f(x) -> np.ndarray``.
    """
    return sp.lambdify(sp.Symbol("x"), expr, modules=["numpy"])

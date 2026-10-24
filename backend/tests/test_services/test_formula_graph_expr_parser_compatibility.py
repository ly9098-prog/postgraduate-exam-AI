"""Real compatibility baseline for formula graph expression validation."""

from __future__ import annotations

import pytest

from app.services.formula_graph_expr_parser import validate_expression


class TestValidateExpression:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_expression("")
        with pytest.raises(ValueError, match="empty"):
            validate_expression("   ")

    def test_simple_polynomial_accepted(self):
        validate_expression("x**2 + 2*x + 1")

    def test_trig_accepted(self):
        validate_expression("sin(x)")

    def test_abs_accepted(self):
        validate_expression("abs(x)")

    def test_syntax_error_raises(self):
        with pytest.raises(ValueError, match="syntax"):
            validate_expression("x +* 2")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            validate_expression("x" * 501)

    def test_attribute_access_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            validate_expression("x.__class__")

    def test_lambda_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            validate_expression("lambda x: x")

    def test_subscript_forbidden(self):
        with pytest.raises(ValueError, match="Forbidden"):
            validate_expression("x[0]")

    def test_underscore_name_forbidden(self):
        with pytest.raises(ValueError, match="Invalid identifier"):
            validate_expression("_x")

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown function"):
            validate_expression("unknown_func(x)")

    def test_nested_expression_accepted(self):
        validate_expression("sin(cos(x))")

    def test_arithmetic_accepted(self):
        validate_expression("x**3 - 2*x**2 + x - 1")

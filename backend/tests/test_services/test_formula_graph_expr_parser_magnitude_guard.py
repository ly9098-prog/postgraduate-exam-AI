import pytest

from app.services.formula_graph_expr_parser import parse_expression, validate_expression


@pytest.mark.parametrize(
    "expr",
    [
        "10**10**10",
        "9**9**9**9",
        "(10**1000)**1000",
        "2**(10**7)",
        "(x*0+10)**(10**9)",
        "(-7)**(10**8)",
        "1/(3**(10**8))",
    ],
)
def test_huge_power_rejected_before_sympy(expr):
    with pytest.raises(ValueError):
        validate_expression(expr)


@pytest.mark.parametrize(
    "expr",
    [
        "x**2",
        "2**x",
        "10**3",
        "sin(x)**2",
        "x**0.5",
        "x**100",
        "exp(x)",
        "2**64",
        "x**3 - 2*x**2 + x - 1",
        "1/(1 + exp(-x))",
        "(x+1)**(1/3)",
    ],
)
def test_ordinary_expressions_still_parse(expr):
    validate_expression(expr)
    parse_expression(expr)

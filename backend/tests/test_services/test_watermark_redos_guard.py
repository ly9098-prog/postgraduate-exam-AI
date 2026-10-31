import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import watermark_service as ws


@pytest.mark.parametrize(
    "pattern",
    [r"(a|a?)+", r"(a|aa)+", r"(\w+\s?)*", r"(a+)+", r"(.*a){10}", r"(?:a|b|ab)*c"],
)
def test_catastrophic_patterns_rejected(pattern):
    with pytest.raises(ValueError, match="ReDoS"):
        ws._validate_pattern(pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        *ws.DEFAULT_WATERMARK_PATTERNS,
        r"^\d+$",
        r"watermark",
        r"(foo|bar)",
        r"^(仅供参考|内部资料).*$",
        r"(abc)+",
        r"\d{1,3}(,\d{3})*",
    ],
)
def test_ordinary_patterns_accepted(pattern):
    ws._validate_pattern(pattern)


def test_create_rule_validates_non_exact_rule_types():
    db = SimpleNamespace(add=MagicMock(), flush=AsyncMock(), refresh=AsyncMock(), commit=AsyncMock())
    with pytest.raises(ValueError):
        asyncio.run(ws.create_rule(db, r"(a|a?)+", rule_type="custom"))


def test_create_rule_rejects_unknown_rule_type():
    db = SimpleNamespace(add=MagicMock(), flush=AsyncMock(), refresh=AsyncMock(), commit=AsyncMock())
    with pytest.raises(ValueError, match="rule_type"):
        asyncio.run(ws.create_rule(db, "abc", rule_type="bogus"))


def test_load_rules_skips_catastrophic_stored_patterns():
    ws.invalidate_cache()
    rules = [
        SimpleNamespace(rule_type="custom", pattern=r"(a|a?)+"),
        SimpleNamespace(rule_type="regex", pattern=r"^ok$"),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rules
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    compiled = asyncio.run(ws.load_rules(db))
    ws.invalidate_cache()
    assert [p.pattern for p in compiled] == ["^ok$"]


def test_match_watermark_bounds_line_length():
    seen = []

    class Pat:
        def search(self, text):
            seen.append(len(text))
            return None

    ws.match_watermark("x" * 100000, [Pat()])
    assert seen and seen[0] <= ws._MAX_MATCH_CHARS

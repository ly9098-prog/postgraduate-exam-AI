"""Provider classification precedence, complete tuples and short-circuit behavior."""

import itertools

import pytest

from app.services.ai import provider_exception as module

OUTCOMES = {
    "auth": ("ai_provider_auth_failed", False, "fallback"),
    "rate": ("ai_provider_rate_limited", True, "fallback"),
    "transient": ("ai_provider_transient", True, "fallback"),
    "model": ("ai_provider_model_not_found", False, "fallback"),
    "request": ("ai_provider_request_incompatible", False, "fallback"),
    "vision": ("vision_unavailable", False, "vision_unavailable"),
    "other": ("ai_provider_error", False, "fallback"),
}
KINDS = [
    ("auth", "auth"),
    ("rate_limit", "rate"),
    ("transient", "transient"),
    ("model_not_found", "model"),
    ("invalid_request", "request"),
    ("parameter_unsupported", "request"),
    ("vision_unsupported", "vision"),
    ("", "other"),
]
STATUSES = [
    (401, "auth"),
    (403, "auth"),
    (429, "rate"),
    (408, "transient"),
    (425, "transient"),
    (500, "transient"),
    (502, "transient"),
    (503, "transient"),
    (504, "transient"),
    (404, "other"),
    (None, "other"),
]
TEXTS = [
    ("INVALID_API_KEY", "auth"),
    ("QUOTA EXCEEDED", "rate"),
    ("CONNECTION RESET", "transient"),
    ("IMAGE rejected", "vision"),
    ("unknown", "other"),
]


class ProviderError(Exception):
    def __init__(self, message="unknown", **attributes):
        super().__init__(message)
        self.__dict__.update(attributes)


def test_typed_status_text_and_visual_priority_cross_product():
    ranks = list(OUTCOMES)
    for kind, status, text, visual in itertools.product(
        KINDS, STATUSES, TEXTS, (False, True)
    ):
        signals = [kind[1], status[1], text[1]]
        if not visual:
            signals = [signal for signal in signals if signal != "vision"]
        winner = min(signals, key=ranks.index)
        exc = ProviderError(
            text[0], error_kind=kind[0], status_code=status[0], retryable=False
        )
        assert (
            module.classify_ai_provider_exception(exc, visual=visual)
            == OUTCOMES[winner]
        ), (kind, status, text, visual)


@pytest.mark.parametrize(
    "text",
    [
        "invalid_api_key",
        "invalid api-key",
        "authentication",
        "unauthorized",
        "forbidden",
        "rate limit",
        "rate_limit",
        "too many requests",
        "quota",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection error",
        "image",
        "vision",
        "multimodal",
        "image_url",
        "content type",
    ],
)
def test_each_historical_text_signal_returns_the_full_tuple(text):
    categories = ["auth"] * 5 + ["rate"] * 4 + ["transient"] * 5 + ["vision"] * 5
    words = [
        "invalid_api_key",
        "invalid api-key",
        "authentication",
        "unauthorized",
        "forbidden",
        "rate limit",
        "rate_limit",
        "too many requests",
        "quota",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection error",
        "image",
        "vision",
        "multimodal",
        "image_url",
        "content type",
    ]
    expected = OUTCOMES[categories[words.index(text)]]
    assert (
        module.classify_ai_provider_exception(ProviderError(text.upper()), visual=True)
        == expected
    )


@pytest.mark.parametrize(
    "status,text,expected",
    [
        (404, "API error: 401", "other"),
        ("429", "authentication", "auth"),
        ("invalid", "status_code=503", "transient"),
        (None, "status: 403", "auth"),
        (None, "status_code=403", "auth"),
        (None, "status = 429", "rate"),
        (None, "api error: 502", "transient"),
        (None, "status_code=404", "other"),
        (None, "status=404 then status=503", "other"),
    ],
)
def test_status_conversion_precedence_and_first_regex_match(status, text, expected):
    exc = ProviderError(text, status_code=status, retryable=False)
    assert (
        module.classify_ai_provider_exception(exc, visual=False) == OUTCOMES[expected]
    )


@pytest.mark.parametrize(
    "signal,expected",
    [("auth", "auth"), ("rate_limit", "rate"), ("transient", "transient")],
)
def test_typed_signal_skips_its_text_predicate_and_later_branches(
    monkeypatch, signal, expected
):
    calls = []

    def contains(text, tokens):
        calls.append(tokens)
        return False

    monkeypatch.setattr(module, "_contains_any", contains)
    result = module.classify_ai_provider_exception(
        ProviderError(error_kind=signal), visual=True
    )
    assert result == OUTCOMES[expected]
    assert len(calls) == {"auth": 0, "rate_limit": 1, "transient": 2}[signal]


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),
        (False, False),
        (0, False),
        ("", False),
        ("false", True),
        ([], False),
        ([1], True),
    ],
)
def test_unknown_error_preserves_typed_retryability(value, expected):
    exc = ProviderError(retryable=value)
    assert module.classify_ai_provider_exception(exc, visual=False) == (
        "ai_provider_error",
        expected,
        "fallback",
    )


def test_metadata_order_and_unknown_retryable_truth_test():
    events = []

    class Retry:
        def __bool__(self):
            events.append("retry_bool")
            return False

    class Error:
        def __bool__(self):
            events.append("error_bool")
            return True

        def __str__(self):
            events.append("str")
            return "UNKNOWN"

        def __getattr__(self, name):
            events.append(name)
            return {"error_kind": "", "retryable": Retry(), "status_code": None}[name]

    assert (
        module.classify_ai_provider_exception(Error(), visual=False)
        == OUTCOMES["other"]
    )
    assert events == [
        "error_bool",
        "str",
        "error_kind",
        "retryable",
        "status_code",
        "retry_bool",
    ]


@pytest.mark.parametrize("kind", [RuntimeError, KeyboardInterrupt])
def test_unexpected_status_conversion_error_is_not_swallowed(kind):
    error = kind("status")

    class Raw:
        def __int__(self):
            raise error

    with pytest.raises(kind) as caught:
        module.classify_ai_provider_exception(
            ProviderError(status_code=Raw()), visual=False
        )
    assert caught.value is error


def test_failure_predicates_keep_original_module_lookup_live(monkeypatch):
    calls = []

    def next_predicate(text, tokens):
        calls.append(("new", tokens))
        return True

    def first_predicate(text, tokens):
        calls.append(("old", tokens))
        monkeypatch.setattr(module, "_contains_any", next_predicate)
        return False

    monkeypatch.setattr(module, "_contains_any", first_predicate)
    assert (
        module.classify_ai_provider_exception(ProviderError(), visual=False)
        == OUTCOMES["rate"]
    )
    assert [name for name, _ in calls] == ["old", "new"]


def test_retryability_is_not_coerced_in_a_recognized_branch():
    class Retry:
        def __bool__(self):
            pytest.fail("recognized category must not coerce retryability")

    assert (
        module.classify_ai_provider_exception(
            ProviderError(error_kind="auth", retryable=Retry()), visual=False
        )
        == OUTCOMES["auth"]
    )

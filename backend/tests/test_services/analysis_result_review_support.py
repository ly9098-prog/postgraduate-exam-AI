"""Independent callback values and traces for post-provider result contracts."""

from types import SimpleNamespace

from app.services.ai import analysis_result_review as module
from app.services.ai.analysis_validation import AnalysisUsage, GroundingValidation
from tests.test_services.test_ai_analysis_result_review import dependencies


def review_harness(monkeypatch, *, fail_at=None, failure=None):
    h = SimpleNamespace(
        raw=object(), parsed={"mistake_diagnosis": object()}, valid=object(),
        usage=AnalysisUsage("before", False, 0, 3, 4),
        grounding=GroundingValidation(True, "grounded"), ack=object(), events=[],
        requests=[], constructed=[], result_response=object(),
    )
    h.result = {"content": h.raw}
    h.invocation = SimpleNamespace(result=h.result, runtime=object())
    h.kwargs = dependencies(image_data_urls=[object()], expected_answer_check=object())
    original_constructor = module.ReviewedAnalysis
    original_request = module.VisualValidationRequest

    def record(name, args, kwargs):
        h.events.append((name, args, kwargs))
        if name == fail_at:
            raise failure

    def sync(name, result):
        def call(*args, **kwargs):
            record(name, args, kwargs)
            return result

        return call

    async def reconcile(*args, **kwargs):
        record("reconcile", args, kwargs)
        return h.grounding

    def request(**kwargs):
        record("request", (), kwargs)
        h.requests.append(kwargs.copy())
        return original_request(**kwargs)

    def constructor(**kwargs):
        record("constructor", (), kwargs)
        h.constructed.append(kwargs.copy())
        return original_constructor(**kwargs)

    h.kwargs.update(parse_content=sync("parse", h.parsed), validate_content=sync("validate", h.valid))
    h.kwargs["build_usage"] = sync("usage", h.usage)
    monkeypatch.setattr(module, "VisualValidationRequest", request)
    monkeypatch.setattr(module, "reconcile_visual_evidence", reconcile)
    monkeypatch.setattr(module, "detect_visual_ack_failure", sync("ack", h.ack))
    monkeypatch.setattr(module, "ReviewedAnalysis", constructor)
    return h


def outcome_harness(monkeypatch, *, kind="valid", fail_at=None, failure=None):
    h = SimpleNamespace(events=[], response=object())
    h.review = SimpleNamespace(
        ack_failure=object() if kind == "ack" else None,
        parsed_valid=kind != "parse", parsed={"diagnosis": object()},
        grounding=GroundingValidation(kind != "repair", "reason"),
        usage=AnalysisUsage("evidence", True, 2, 3, 4),
    )

    def record(name, args, kwargs):
        h.events.append((name, args, kwargs))
        if name == fail_at:
            raise failure

    def ack(*args, **kwargs):
        record("ack", args, kwargs)
        return h.response

    def parse(*args, **kwargs):
        record("parse", args, kwargs)
        return h.response

    def log(*args, **kwargs):
        record("log", args, kwargs)

    def async_call(name):
        async def call(*args, **kwargs):
            record(name, args, kwargs)
            return h.response

        return call

    h.db = object()
    h.kwargs = dict(
        wrong_question=SimpleNamespace(id=7), user_id=8, context={"question": object()},
        result={"model": object()}, image_data_urls=[object()], input_signature=object(),
        model_signature=object(), expected_answer_check=object(), effective_force=object(),
        runtime=object(), visual_evidence_is_valid=object(), max_tokens=800,
        logger=SimpleNamespace(info=log), visual_ack_failure=ack,
        grounding_repair=async_call("repair"), valid_outcome=async_call("valid"),
    )
    monkeypatch.setattr(module, "parse_failed_response", parse)
    return h


def expected_outcome(h, kind):
    values = h.kwargs
    if kind == "ack":
        return (), dict(
            wrong_question_id=7, result=values["result"],
            image_data_urls=values["image_data_urls"], usage=h.review.usage,
            visual_ack_retried=True, failure=h.review.ack_failure, logger=values["logger"],
        )
    keys = [
        "wrong_question", "user_id", "context", "result", "input_signature",
        "model_signature", "expected_answer_check", "effective_force", "runtime", "logger",
        "image_data_urls",
    ]
    kwargs = {key: values[key] for key in keys}
    kwargs.update(grounding=h.review.grounding, usage=h.review.usage)
    if kind == "valid":
        kwargs.update(
            parsed=h.review.parsed,
            visual_evidence_is_valid=values["visual_evidence_is_valid"],
            max_tokens=values["max_tokens"],
        )
    return (h.db,), kwargs


class ReadProbe:
    def __init__(self, values, reads, prefix):
        self._values, self._reads, self._prefix = values, reads, prefix

    def __getattr__(self, name):
        self._reads.append(self._prefix + "." + name)
        return getattr(self._values, name)

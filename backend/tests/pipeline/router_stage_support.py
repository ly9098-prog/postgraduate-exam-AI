"""Deterministic router-stage ports; no model, Redis or database is contacted."""

from types import SimpleNamespace

from app.features import candidate_evaluator, quality_gate, token_budget
from app.features import pipeline_orchestrator as orchestrator
from app.features.ocr_fix import metrics, router


def result_for(text="fixed", **overrides):
    values = dict(
        fixed_text=text,
        model_used="fixture-model",
        confidence=0.9,
        tokens_used=7,
        duration_ms=12,
        raw_response="",
        risk_flags=None,
        safety=None,
        metadata={},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def record(harness, name, result=None):
    def callback(*args, **kwargs):
        harness.events.append((name, args, kwargs))
        return result

    return callback


def router_harness(monkeypatch):
    h = SimpleNamespace(
        events=[],
        config={"ocr_filter_sensitive": False},
        results={},
        allowed=True,
        gate_mode="off",
        shadow_error=None,
        shadow_decisions=[object(), object()],
    )
    h.pipeline = orchestrator.ImportPipeline()
    h.pipeline.pipeline_id = "router-contract"
    h.blocks = [{"page": 1, "block_index": 4, "normalized_text": "original"}]
    h.decision = SimpleNamespace(
        decision=candidate_evaluator.CandidateDecision.ACCEPT,
        accepted_text="accepted",
        reason_code="safe",
        risk_flags=["risk"],
        diff={"changed": True},
    )

    install_model_ports(monkeypatch, h)
    install_classification_ports(monkeypatch, h)
    install_quality_ports(monkeypatch, h)
    return h


def install_model_ports(monkeypatch, h):
    async def config(opts, db):
        h.events.append(("config", (opts, db), {}))
        return h.config

    async def fix(**kwargs):
        h.events.append(("fix", (), kwargs))
        value = h.results.get(kwargs["context"]["block_index"], result_for())
        if isinstance(value, BaseException):
            raise value
        return value

    async def check(estimated, config):
        h.events.append(("check", (estimated, config), {}))
        return h.allowed

    async def usage(tokens):
        h.events.append(("usage", (tokens,), {}))

    h.router = SimpleNamespace(configure=record(h, "configure"), fix=fix)
    h.metrics = SimpleNamespace(
        **{
            method: record(h, method)
            for method in (
                "record_classification",
                "record_correction",
                "record_failure",
                "record_unchanged",
                "flush",
            )
        }
    )
    monkeypatch.setattr(h.pipeline, "_build_router_config", config)
    monkeypatch.setattr(router, "OCRFixRouter", lambda: h.router)
    monkeypatch.setattr(metrics, "OcrCorrectionMetrics", lambda: h.metrics)
    monkeypatch.setattr(token_budget, "estimate_tokens", record(h, "estimate", 5))
    monkeypatch.setattr(token_budget, "check_token_limit", check)
    monkeypatch.setattr(token_budget, "record_token_usage", usage)


def install_classification_ports(monkeypatch, h):
    monkeypatch.setattr(orchestrator, "_detect_noise", record(h, "noise", 0.41))
    monkeypatch.setattr(
        orchestrator, "_detect_structure_abnormal", record(h, "structure", 0.31)
    )
    monkeypatch.setattr(
        orchestrator, "_should_correct", lambda score, config, **kw: True
    )
    monkeypatch.setattr(orchestrator, "safe_text_preview", lambda text: "preview")
    monkeypatch.setattr(orchestrator, "_safe_text_summary", lambda text: {"text": text})
    monkeypatch.setattr(
        orchestrator, "_get_domain_quality_gate_mode", lambda: h.gate_mode
    )
    monkeypatch.setattr(
        orchestrator,
        "logger",
        SimpleNamespace(
            **{name: record(h, name) for name in ("info", "warning", "debug")}
        ),
    )


def install_quality_ports(monkeypatch, h):
    def evaluate(**kwargs):
        h.events.append(("evaluate", (), kwargs))
        return h.decision

    def shadow(before, after, context):
        h.events.append(("shadow", (before, after, context), {}))
        if h.shadow_error is not None:
            raise h.shadow_error
        return h.shadow_decisions

    def shadow_record(decision, context):
        h.events.append(("shadow_record", (decision, context), {}))
        return {"decision": "fixture"}

    monkeypatch.setattr(
        candidate_evaluator, "get_evaluator", lambda: SimpleNamespace(evaluate=evaluate)
    )
    monkeypatch.setattr(
        quality_gate, "CompositeQualityGate", lambda: SimpleNamespace(evaluate=shadow)
    )
    monkeypatch.setattr(quality_gate, "record_shadow_decision", shadow_record)

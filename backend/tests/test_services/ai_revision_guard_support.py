"""Instrumented database, grounding and observation ports for the real revision guard."""

import logging
from types import SimpleNamespace

from app.services.ai import revision_guard as module


def observe(h, name, value=None):
    h.events.append(name)
    h.records.setdefault(name, []).append(value)
    if name in h.hooks:
        return h.hooks[name](value)


def fail_at(h, name, error):
    def fail(_):
        raise error

    h.hooks[name] = fail


def install_ports(monkeypatch, h):
    async def scalar(query):
        observe(h, "scalar", query)
        if h.wait:
            await h.wait()
        return h.revision

    def grounding(**kwargs):
        name = "current" if not h.records.get("current") else "historical"
        observe(h, name, kwargs)
        return h.current if name == "current" else h.historical

    def signature(value):
        observe(h, "signature", value)
        return h.current_signature if value is h.current else h.historical_signature

    def response():
        observe(h, "response")
        return h.content

    h.db = SimpleNamespace(scalar=scalar)
    monkeypatch.setattr(module, "build_answer_grounding", grounding)
    monkeypatch.setattr(module, "grounding_fact_signature", signature)
    monkeypatch.setattr(module, "build_revision_drift_analysis", response)


def install_observations(monkeypatch, h):
    class Clock:
        @staticmethod
        def now(zone):
            observe(h, "now", zone)
            return SimpleNamespace(isoformat=lambda: observe(h, "isoformat") or "stamp")

    original = logging.getLogger

    def logger(name=None):
        if name == module.__name__:
            observe(h, "get_logger", name)
            return SimpleNamespace(warning=lambda *args: observe(h, "warning", args))
        return original(name)

    monkeypatch.setattr(logging, "getLogger", logger)
    monkeypatch.setattr(module, "datetime", Clock)


def make_harness(monkeypatch):
    h = SimpleNamespace(
        events=[],
        records={},
        hooks={},
        wait=None,
        question=SimpleNamespace(
            id=11,
            question_type="single",
            content="new",
            options={"A": "new"},
            answer="B",
            current_version_id=17,
        ),
        wrong=SimpleNamespace(
            id=3, question_id=11, question_version_id=7, wrong_answer="A"
        ),
        revision=SimpleNamespace(
            question_type="old_type", content="old", options={"A": "old"}, answer="A"
        ),
        current={"current": []},
        historical={"historical": []},
        current_signature="new",
        historical_signature="old",
        content=object(),
    )
    install_ports(monkeypatch, h)
    install_observations(monkeypatch, h)
    return h


async def execute(h):
    return await module.check_analysis_revision_drift(
        h.db, wrong_question=h.wrong, question=h.question
    )

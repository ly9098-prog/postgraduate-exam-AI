"""Load the original token module for optional local contract replay."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

from app.services.practice import batch_token

NOW = 1800000000
NOW_DT = datetime.fromtimestamp(NOW, timezone.utc).replace(tzinfo=None)


@pytest.fixture
def token_module():
    source = os.environ.get("PRACTICE_TOKEN_BASELINE")
    if not source:
        return batch_token
    module = ModuleType("practice_token_baseline")
    module.__file__ = source
    exec(compile(Path(source).read_text(), source, "exec"), module.__dict__)
    return module


def payload(**overrides):
    result = {
        "v": 2,
        "uid": 7,
        "rid": "submit-1",
        "rec_rid": "rec-1",
        "sid": 3,
        "mode": "random",
        "iat": NOW,
        "exp": NOW + 86400,
        "questions": [[2, 202], [1, 101]],
    }
    result.update(overrides)
    return result


def session(**overrides):
    result = {
        "subject_id": 3,
        "mode": "random",
        "request_id": "submit-1",
        "started_at": NOW_DT.isoformat(),
        "finished_at": NOW_DT.isoformat(),
    }
    result.update(overrides)
    return result


@pytest.fixture
def validate(token_module, monkeypatch):
    def run(value=None, *, ids=None, meta=None, answers=None, user_id=7):
        current = payload() if value is None else value
        monkeypatch.setattr(
            token_module, "_decode_practice_batch_token", lambda _: current
        )
        monkeypatch.setattr(token_module, "utcnow", lambda: NOW_DT)
        return token_module._validate_practice_batch_token(
            "signed",
            user_id=user_id,
            question_ids=[1, 2] if ids is None else ids,
            session_meta=session() if meta is None else meta,
            answers=[{"request_id": "rec-1"}] if answers is None else answers,
        )

    return run

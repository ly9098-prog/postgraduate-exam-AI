import importlib.util
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.features.question_pipeline import normalizer
from app.models.question import Question

_SCRIPT_PATH = _BACKEND_ROOT / "scripts" / "backfill_question_hash.py"
_SPEC = importlib.util.spec_from_file_location("backfill_question_hash_script", _SCRIPT_PATH)
backfill_script = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(backfill_script)
backfill_question_hash = backfill_script.backfill_question_hash


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return _Scalars(self.values)


class _Db:
    def __init__(self, batches):
        self.batches = list(batches)
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _statement):
        if self.batches:
            return _Result(self.batches.pop(0))
        return _Result([])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _question(question_id=1, question_hash=None, content=None, options=None, answer="A"):
    return Question(
        id=question_id,
        subject="math2",
        question_type="single_choice",
        content={"text": "题干"} if content is None else content,
        options={"A": "1", "B": "2"} if options is None else options,
        answer=answer,
        question_hash=question_hash,
    )


def _question_without_default_options(question_id=1, question_hash=None, content=None, answer="A"):
    question = _question(
        question_id=question_id,
        question_hash=question_hash,
        content=content,
        answer=answer,
    )
    question.options = None
    return question


class _QuestionWithConcurrentHash(Question):
    @property
    def question_hash(self):
        return self._question_hash

    @question_hash.setter
    def question_hash(self, value):
        if getattr(self, "_lock_hash", False):
            return
        self._question_hash = value


@pytest.mark.asyncio
async def test_backfill_question_hash_dry_run_does_not_write(monkeypatch):
    question = _question()
    db = _Db([[question], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=False, batch_size=10, limit=None)

    assert stats == {"scanned": 1, "updated": 1, "skipped": 0, "errors": 0}
    assert question.question_hash is None
    assert db.rollbacks == 1
    assert db.commits == 0


@pytest.mark.asyncio
async def test_backfill_question_hash_apply_writes_hash(monkeypatch):
    question = _question()
    db = _Db([[question], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=True, batch_size=10, limit=None)

    assert stats["updated"] == 1
    assert question.question_hash == normalizer.build_question_hash(
        "题干",
        question.options,
        question.answer,
    )
    assert len(question.question_hash) == 32
    assert db.commits == 1
    assert db.rollbacks == 0


@pytest.mark.asyncio
async def test_backfill_question_hash_uses_available_payload(monkeypatch):
    question = _question_without_default_options(content={}, answer="A")
    db = _Db([[question], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=True, batch_size=10, limit=None)

    assert stats == {"scanned": 1, "updated": 1, "skipped": 0, "errors": 0}
    assert question.question_hash == normalizer.build_question_hash(
        "",
        None,
        "A",
    )


@pytest.mark.asyncio
async def test_backfill_question_hash_reads_chinese_content_keys(monkeypatch):
    question_with_tigan = _question(question_id=1, content={"题干": "中文题干"})
    question_with_timu = _question(question_id=2, content={"题目": "中文题目"})
    db = _Db([[question_with_tigan, question_with_timu], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=True, batch_size=10, limit=None)

    assert stats == {"scanned": 2, "updated": 2, "skipped": 0, "errors": 0}
    assert question_with_tigan.question_hash == normalizer.build_question_hash(
        "中文题干",
        question_with_tigan.options,
        question_with_tigan.answer,
    )
    assert question_with_timu.question_hash == normalizer.build_question_hash(
        "中文题目",
        question_with_timu.options,
        question_with_timu.answer,
    )


@pytest.mark.asyncio
async def test_backfill_question_hash_does_not_stringify_unknown_dict_content(monkeypatch):
    question = _question_without_default_options(
        content={"unknown": "不要被当作题干"},
        answer=None,
    )
    db = _Db([[question], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=True, batch_size=10, limit=None)

    assert stats == {"scanned": 1, "updated": 0, "skipped": 1, "errors": 0}
    assert question.question_hash is None


@pytest.mark.asyncio
async def test_backfill_question_hash_does_not_overwrite_existing_hash_on_fetched_object(monkeypatch):
    question = _question(question_hash="existing-hash")
    db = _Db([[question], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=True, batch_size=10, limit=None)

    assert stats == {"scanned": 1, "updated": 0, "skipped": 1, "errors": 0}
    assert question.question_hash == "existing-hash"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_backfill_question_hash_checks_hash_again_before_assignment(monkeypatch):
    question = _QuestionWithConcurrentHash(
        id=1,
        subject="math2",
        question_type="single_choice",
        content={"text": "题干"},
        options={"A": "1", "B": "2"},
        answer="A",
    )
    question._question_hash = "concurrent-hash"
    question._lock_hash = True
    db = _Db([[question], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=True, batch_size=10, limit=None)

    assert stats == {"scanned": 1, "updated": 0, "skipped": 1, "errors": 0}
    assert question.question_hash == "concurrent-hash"


@pytest.mark.asyncio
async def test_backfill_question_hash_respects_limit_across_batches(monkeypatch):
    first = _question(question_id=1)
    second = _question(question_id=2)
    third = _question(question_id=3)
    db = _Db([[first, second], [third], []])
    monkeypatch.setattr(backfill_script, "async_session", lambda: db)

    stats = await backfill_question_hash(apply=True, batch_size=2, limit=2)

    assert stats == {"scanned": 2, "updated": 2, "skipped": 0, "errors": 0}
    assert first.question_hash
    assert second.question_hash
    assert third.question_hash is None
    assert db.commits == 1

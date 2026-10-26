"""Issue-time baseline contracts, first exercised against the original entry."""

from types import SimpleNamespace

import pytest

from app.services.practice import knowledge_session_summary as svc
from tests.practice.knowledge_summary_support import Database, root_port, state


async def issue(db, scope, questions=None, revisions=None, subject=7):
    return await svc.build_issue_knowledge_context(
        db,
        user_id=7,
        knowledge_scope=scope,
        questions=[SimpleNamespace(id=10)] if questions is None else questions,
        revision_ids={10: 101} if revisions is None else revisions,
        practice_subject_id=subject,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,questions,revisions",
    [
        (None, None, None),
        ({}, None, None),
        ({"root_id": 12, "knowledge_point_ids": [12]}, [], None),
        ({"root_id": 12, "knowledge_point_ids": [0, -1]}, None, None),
        ({"root_id": 12, "knowledge_point_ids": [12]}, None, {}),
    ],
)
async def test_issue_early_returns_have_no_sql(scope, questions, revisions):
    db = Database()
    assert await issue(db, scope, questions, revisions) is None
    assert db.events == []


@pytest.mark.asyncio
async def test_issue_signed_scope_preserves_order_and_96_point_cap(monkeypatch):
    ids = [12, 3, *range(1, 121), 12, 0, -1]
    ordered = list(dict.fromkeys(value for value in ids if value > 0))
    db = Database(execute=[range(1, 121)], scalars=[[state(12, 72.456, 0.87654)]])
    root_port(
        monkeypatch,
        db,
        {
            "subtree_mastery_score": "64.55",
            "subtree_coverage_ratio": 0.45678,
            "subtree_weak_knowledge_points": "4",
            "subtree_reliable_knowledge_points": 70,
            "subtree_trainable_knowledge_points": 120,
        },
    )
    result = await issue(
        db,
        {
            "root_id": 12,
            "root_name": "signed",
            "knowledge_point_ids": ids,
            "subject_id": 99,
            "syllabus_version_id": "5",
            "include_descendants": True,
        },
    )
    assert result["v"] == 2
    assert result["subject_id"] == 7 and result["syllabus_version_id"] == 5
    assert result["scope_ids"] == result["served_ids"] == ordered
    assert result["scope_count"] == result["served_count"] == 120
    assert result["baseline"]["root"] == ["64.55", 0.45678, 4, 70, 120]
    assert [row[0] for row in result["baseline"]["points"]] == ordered[:96]
    assert result["baseline"]["points"][:2] == [
        [12, 72.46, 0.8765, 3],
        [3, None, 0.0, 0],
    ]
    assert db.events == ["execute", "scalars", ("root", 12)]
    assert "SELECT DISTINCT" in db.sql[0][1]
    assert "knowledge_points.is_active IS true" in db.sql[0][1]
    assert db.sql[0][2]["question_version_id_1"] == [101]
    assert set(db.sql[0][2]["knowledge_point_id_1"]) == set(ordered)
    assert db.sql[1][2] == {"user_id_1": 7, "knowledge_point_id_1": ordered[:96]}


@pytest.mark.asyncio
async def test_issue_no_represented_points_still_uses_root_aggregate(monkeypatch):
    db = Database(execute=[[]])
    root_port(
        monkeypatch,
        db,
        {
            "status": "no_data",
            "mastery_score": 21,
            "subtree_mastery_score": 99,
            "trainable_question_count": 2,
        },
    )
    result = await issue(
        db,
        {
            "root_id": 12,
            "knowledge_point_ids": [12],
            "subject_id": 9,
        },
        subject=None,
    )
    assert result["practice_mode"] == "knowledge_point"
    assert result["subject_id"] == 9
    assert result["baseline"] == {"root": [21, 0.0, 0, 0, 1], "points": []}
    assert result["served_count"] == 0
    assert db.events == ["execute", ("root", 12)]


@pytest.mark.asyncio
async def test_issue_retains_revision_duplicates_patch_ports_and_missing_root(
    monkeypatch,
):
    db = Database(execute=[[12]], scalars=[[state(12)]])
    root_port(monkeypatch, db)
    seen = []
    monkeypatch.setattr(svc, "_MAX_BASELINE_POINTS", 1)
    monkeypatch.setattr(svc, "_CONTEXT_VERSION", 8)
    monkeypatch.setattr(
        svc,
        "_compact_point_baseline",
        lambda value, kp_id: (
            seen.append((value, kp_id, list(db.events))) or ["patched"]
        ),
    )
    result = await issue(
        db,
        {"root_id": 12, "knowledge_point_ids": [12]},
        [SimpleNamespace(id=10), SimpleNamespace(id="10")],
    )
    assert result["v"] == 8
    assert result["baseline"] == {"root": None, "points": [["patched"]]}
    assert db.sql[0][2]["question_version_id_1"] == [101, 101]
    assert seen[0][1:] == (12, ["execute", "scalars", ("root", 12)])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel,expected",
    [
        ("execute", ["execute"]),
        ("scalars", ["execute", "scalars"]),
        ("root", ["execute", "scalars", ("root", 12)]),
    ],
)
async def test_issue_port_errors_propagate_at_original_stage(
    monkeypatch, channel, expected
):
    error = RuntimeError(channel)
    db = Database(execute=[[12]], scalars=[[]], failure=(channel, error))
    root_port(monkeypatch, db, error=error if channel == "root" else None)
    with pytest.raises(RuntimeError) as caught:
        await issue(db, {"root_id": 12, "knowledge_point_ids": [12]})
    assert caught.value is error
    assert db.events == expected


@pytest.mark.asyncio
async def test_issue_invalid_signed_fields_fail_after_original_prior_work(monkeypatch):
    db = Database(execute=[[12]], scalars=[[]])
    root_port(monkeypatch, db)
    with pytest.raises(ValueError):
        await issue(db, {"root_id": 12, "knowledge_point_ids": ["invalid"]})
    assert db.events == []
    with pytest.raises(ValueError):
        await issue(
            db,
            {"root_id": 12, "knowledge_point_ids": [12], "subject_id": "bad"},
            subject=None,
        )
    assert db.events == ["execute", "scalars", ("root", 12)]

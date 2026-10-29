"""Wrong-book request contracts with fake database and service ports."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api.v1 import wrong_questions as api


def wrong(**overrides):
    values = dict(
        id=4,
        question_id=8,
        question_version_id=12,
        wrong_answer="B",
        error_type="concept",
        review_count=2,
        created_at=datetime(2026, 10, 30),
        updated_at=datetime(2026, 10, 30),
        ai_analysis=None,
        mastered=False,
        last_review_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def question(**overrides):
    values = dict(
        id=8,
        subject_id=1,
        subject_ref=SimpleNamespace(code="math", name="Math"),
        question_type="single_choice",
        content={"text": "stem"},
        options={"A": "one"},
        answer="A",
        analysis="analysis",
        image_url=[],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("value", [None, 5, "", "return x;", "int x = 1;\nx +=\n 2;"])
def test_text_non_strings_and_code_preserve_dedup_boundary(monkeypatch, value):
    dedup = Mock(side_effect=lambda text: text)
    roman = Mock(side_effect=lambda text: text)
    monkeypatch.setattr(api, "deduplicate_repeated_text", dedup)
    monkeypatch.setattr(api, "_split_inline_roman_subitems", roman)
    result = api._sanitize_text_field(value)
    if not isinstance(value, str) or api._contains_code(value):
        dedup.assert_not_called()
        roman.assert_not_called()
    else:
        dedup.assert_called_once_with(value)
        roman.assert_called_once_with(value)
    if value == "int x = 1;\nx +=\n 2;":
        assert result == "int x = 1;\nx +=2;"


def test_content_keeps_input_and_sanitizes_before_reconcile_and_strip(monkeypatch):
    trace = []
    shared = {"keep": True}
    original = {
        "text": "text",
        "stem": "stem",
        "extra": shared,
        "source_snapshot_url": "private",
        "source_snapshot_full_page": True,
        "visual_regions": [],
        "visual_region_ids": [],
    }
    monkeypatch.setattr(
        api, "_sanitize_text_field", lambda text: trace.append(text) or text.upper()
    )

    def reconcile(value):
        assert value["text"] == "TEXT" and value["stem"] == "STEM"
        assert "source_snapshot_url" in value
        trace.append("reconcile")
        return value

    def strip(value):
        assert "source_snapshot_url" not in value and "visual_regions" not in value
        trace.append("strip")
        return value

    monkeypatch.setattr(api, "reconcile_student_stem_fields", reconcile)
    monkeypatch.setattr(api, "strip_student_segment_metadata", strip)
    result = api._sanitize_content(original)
    assert result is not original and result["extra"] is shared
    assert original["text"] == "text" and original["source_snapshot_url"] == "private"
    assert trace == ["text", "stem", "reconcile", "strip"]


def test_options_copy_rich_values_keep_fallback_and_do_not_dedup(monkeypatch):
    dedup = Mock(side_effect=AssertionError("options must not deduplicate"))
    monkeypatch.setattr(api, "deduplicate_repeated_text", dedup)
    rich = {"text": "", "value": "  a\r\n\r\nb ", "meta": []}
    values = {"A": rich, "B": "x +=\n 2;", "C": None, "D": 8}
    result = api._sanitize_options(values)
    assert result == {
        "A": {"text": "a b", "value": "  a\r\n\r\nb ", "meta": []},
        "B": "x +=2;",
        "C": None,
        "D": 8,
    }
    assert result is not values and result["A"] is not rich
    assert result["A"]["meta"] is rich["meta"] and rich["text"] == ""


@pytest.mark.parametrize(
    "alive,knowledge", [(False, None), (False, []), (True, None), (True, [])]
)
def test_projection_deleted_question_and_empty_knowledge_point_rules(alive, knowledge):
    result = api.enrich_wq(wrong(), question() if alive else None, knowledge)
    assert result.knowledge_points == ([] if alive else None)
    assert result.subject_code == ("math" if alive else None)
    assert result.content == ({"text": "stem", "stem": "stem"} if alive else None)


@pytest.mark.parametrize(
    "analysis,status", [(None, None), ({}, None), ({"text": "old"}, "stale")]
)
def test_projection_analysis_override_keeps_raw_generated_marker(analysis, status):
    value = wrong(
        ai_analysis={"_meta": {"generated_at": " old-marker "}, "text": "raw"}
    )
    response = api.enrich_wq(
        value,
        None,
        ai_analysis_override=analysis,
        ai_analysis_status_override=status,
        wrong_count=0,
        mastery_percent=0.4,
        is_mastered=False,
    )
    assert response.ai_analysis == analysis
    assert response.ai_analysis_generated_at == "old-marker"
    assert response.ai_analysis_status == (status if status is not None else "empty")
    assert response.wrong_count == 0 and response.mastery_percent == 0.4


def test_projection_preserves_arbitrary_extra_named_ports():
    assert api.enrich_wq(wrong(), None, ports=object()).question_id == 8


@pytest.fixture
def ports(monkeypatch):
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    user = SimpleNamespace(id=3)
    monkeypatch.setattr(
        api, "_resolve_product_subject_ids", AsyncMock(return_value={1, 2})
    )
    monkeypatch.setattr(
        api,
        "_load_wrong_detail_view",
        AsyncMock(return_value=(wrong(), question(), [])),
    )
    monkeypatch.setattr(
        api, "_enrich_single_wq_extra", AsyncMock(return_value={"mastery_percent": 0.2})
    )
    monkeypatch.setattr(
        api.error_diagnosis_service,
        "get_latest_diagnosis",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        api.error_diagnosis_service, "serialize_diagnosis", lambda row: {"id": row.id}
    )
    monkeypatch.setattr(api.cache, "delete", AsyncMock())
    return SimpleNamespace(db=db, user=user)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["list_wrong", "get_task_flow"])
async def test_dates_rejected_before_product_scope_or_service(ports, entry):
    kwargs = dict(
        subject_id=None,
        error_type=None,
        topic=None,
        product_scope="invalid",
        date_from=date(2026, 10, 30),
        date_to=date(2026, 10, 29),
        db=ports.db,
        current_user=ports.user,
    )
    if entry == "list_wrong":
        kwargs.update(page=1, page_size=20)
    else:
        kwargs["preview_size"] = 3
    with pytest.raises(HTTPException) as caught:
        await getattr(api, entry)(**kwargs)
    assert caught.value.status_code == 422
    api._resolve_product_subject_ids.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["list_wrong", "get_task_flow"])
async def test_list_and_taskflow_mutate_same_rows_and_read_current_sanitizers(
    ports, monkeypatch, entry
):
    trace = []
    first, second = {"content": "one", "options": {}}, {"content": "two", "options": {}}

    def content(value):
        trace.append(value)
        monkeypatch.setattr(api, "_sanitize_options", lambda options: {"current": True})
        return {"text": value}

    monkeypatch.setattr(api, "_sanitize_content", content)
    if entry == "list_wrong":
        monkeypatch.setattr(
            api.svc, "list_wrong_enriched", AsyncMock(return_value=([first, second], 2))
        )
        result = await api.list_wrong(
            None,
            None,
            None,
            1,
            20,
            None,
            None,
            None,
            ports.db,
            ports.user,
        )
        rows = result["items"]
    else:
        flow = {"groups": [{"items": [first, second]}, {}], "summary": {}}
        monkeypatch.setattr(api.svc, "get_task_flow", AsyncMock(return_value=flow))
        result = await api.get_task_flow(
            None,
            None,
            None,
            3,
            None,
            None,
            None,
            ports.db,
            ports.user,
        )
        assert result is flow
        rows = result["groups"][0]["items"]
    assert rows[0] is first and rows[1] is second
    assert trace == ["one", "two"] and first["options"] == {"current": True}


@pytest.mark.asyncio
async def test_detail_uses_current_question_and_ai_override_after_diagnosis(
    ports, monkeypatch
):
    from app.services import ai_service

    row, current_question, kps = api._load_wrong_detail_view.return_value
    kps.append({"name": "current KP"})
    diagnosis = SimpleNamespace(id=5)
    api.error_diagnosis_service.get_latest_diagnosis.return_value = diagnosis
    evaluate = AsyncMock(return_value={"analysis": None, "status": "stale"})
    monkeypatch.setattr(ai_service, "evaluate_cached_error_analysis", evaluate)
    response = await api.get_wrong(4, ports.db, ports.user)
    assert response.ai_analysis is None and response.ai_analysis_status == "stale"
    assert response.error_diagnosis == {"id": 5}
    evaluate.assert_awaited_once_with(
        ports.db, row, current_question, knowledge_points=kps
    )
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_detail_missing_question_skips_ai_and_missing_record_stops(
    ports, monkeypatch, missing
):
    from app.services import ai_service

    api._load_wrong_detail_view.return_value = (None if missing else wrong(), None, [])
    evaluate = AsyncMock()
    monkeypatch.setattr(ai_service, "evaluate_cached_error_analysis", evaluate)
    if missing:
        with pytest.raises(HTTPException) as caught:
            await api.get_wrong(4, ports.db, ports.user)
        assert caught.value.status_code == 404
        api._enrich_single_wq_extra.assert_not_awaited()
    else:
        response = await api.get_wrong(4, ports.db, ports.user)
        assert response.knowledge_points is None
    evaluate.assert_not_awaited()


@pytest.mark.asyncio
async def test_detail_ai_error_propagates_without_mutating_database(ports, monkeypatch):
    from app.services import ai_service

    monkeypatch.setattr(
        ai_service,
        "evaluate_cached_error_analysis",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await api.get_wrong(4, ports.db, ports.user)
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_diagnosis_legacy_creation_owns_commit_refresh(
    ports, monkeypatch, existing
):
    value, diagnosis = wrong(), SimpleNamespace(id=5)
    monkeypatch.setattr(api.svc, "get_by_id", AsyncMock(return_value=value))
    api.error_diagnosis_service.get_latest_diagnosis.return_value = (
        diagnosis if existing else None
    )
    ensure = AsyncMock(return_value=diagnosis)
    monkeypatch.setattr(api.error_diagnosis_service, "ensure_legacy_diagnosis", ensure)
    assert await api.get_wrong_error_diagnosis(4, ports.db, ports.user) == {"id": 5}
    assert ensure.await_count == (0 if existing else 1)
    assert ports.db.commit.await_count == (0 if existing else 1)
    assert ports.db.refresh.await_count == (0 if existing else 1)


@pytest.mark.asyncio
async def test_confirmation_awaits_cache_patterns_before_live_serializer(
    ports, monkeypatch
):
    diagnosis = SimpleNamespace(id=5)
    monkeypatch.setattr(
        api.error_diagnosis_service,
        "confirm_diagnosis",
        AsyncMock(return_value=diagnosis),
    )

    async def delete(pattern):
        monkeypatch.setattr(
            api.error_diagnosis_service,
            "serialize_diagnosis",
            lambda row: {"late": row.id},
        )

    api.cache.delete.side_effect = delete
    result = await api.confirm_wrong_error_diagnosis(
        4,
        SimpleNamespace(primary_type="concept", secondary_types=[], diagnosis_id=None),
        ports.db,
        ports.user,
    )
    assert result == {"late": 5}
    assert [call.args[0] for call in api.cache.delete.call_args_list] == [
        "wrong_questions:*:3*",
        "stats:*:3*",
        "stats:dashboard*:3*",
    ]
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [False, True])
async def test_batch_success_controls_cache_invalidation_and_response_identity(
    ports, monkeypatch, success
):
    response = {"success": success, "extra": object()}
    monkeypatch.setattr(api.svc, "batch_operate", AsyncMock(return_value=response))
    request = SimpleNamespace(action=SimpleNamespace(value="mark_mastered"), ids=[4, 4])
    if success:
        assert await api.batch_operate(request, ports.db, ports.user) is response
        assert [call.args[0] for call in api.cache.delete.call_args_list] == [
            "wrong_questions:*:3*",
            "stats:*:3*",
            "review:*:3*",
            "stats:dashboard*:3*",
        ]
    else:
        with pytest.raises(HTTPException) as caught:
            await api.batch_operate(request, ports.db, ports.user)
        assert caught.value.status_code == 400
        api.cache.delete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "found,question_alive", [(False, False), (True, False), (True, True)]
)
async def test_detail_join_retains_owner_active_scope_and_missing_kp_rules(
    monkeypatch, found, question_alive
):
    db = SimpleNamespace(execute=AsyncMock())
    value, current = wrong(), question() if question_alive else None
    db.execute.return_value = SimpleNamespace(
        one_or_none=lambda: (value, current) if found else None
    )
    kps = [{"id": 9}]
    loader = AsyncMock(return_value={8: kps})
    monkeypatch.setattr(api, "load_question_kps", loader)
    result = await api._load_wrong_detail_view(db, 3, 4)
    assert result == (
        (value, current, kps if question_alive else []) if found else (None, None, [])
    )
    sql = str(db.execute.call_args.args[0])
    assert "LEFT OUTER JOIN" in sql and "user_id" in sql and "is_active" in sql
    assert loader.await_count == int(found and question_alive)


@pytest.mark.asyncio
@pytest.mark.parametrize("mastered,repetitions", [(False, None), (False, 2), (True, 0)])
async def test_extra_uses_one_version_scoped_aggregate_and_mastery(
    mastered, repetitions
):
    db = SimpleNamespace(execute=AsyncMock())
    next_review = datetime(2026, 11, 1)
    db.execute.return_value = SimpleNamespace(
        one=lambda: SimpleNamespace(
            review_record_count=None,
            repetitions=repetitions,
            schedule_mastered=False,
            next_review_at=next_review,
            last_reviewed_at=None,
        )
    )
    result = await api._enrich_single_wq_extra(db, 3, wrong(mastered=mastered))
    sql = str(db.execute.call_args.args[0])
    assert "question_version_id" in sql and "user_id" in sql and "is_active" in sql
    db.execute.assert_awaited_once()
    assert result["review_record_count"] == 0
    assert result["next_review_at"] == (None if mastered else next_review)
    if mastered:
        assert result["mastery_percent"] == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, "", "  ", "not-supported", " EXAM408 "])
async def test_product_scope_validates_before_query_and_returns_selected_ids(
    monkeypatch, scope
):
    db = SimpleNamespace(execute=AsyncMock())
    subjects = [object()]
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: subjects)
    )
    selector = Mock(return_value={4, 5})
    monkeypatch.setattr(api, "selected_408_subject_ids", selector)
    if scope == "not-supported":
        with pytest.raises(HTTPException) as caught:
            await api._resolve_product_subject_ids(db, scope)
        assert caught.value.status_code == 400
        db.execute.assert_not_awaited()
    else:
        result = await api._resolve_product_subject_ids(db, scope)
        if scope == " EXAM408 ":
            assert result == {4, 5}
            selector.assert_called_once_with(subjects)
        else:
            assert result is None
            db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("alive", [False, True])
async def test_current_question_loader_uses_question_id_and_kp_fallback(
    monkeypatch, alive
):
    db = SimpleNamespace(execute=AsyncMock())
    current = question() if alive else None
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: current)
    loader = AsyncMock(return_value={})
    monkeypatch.setattr(api, "load_question_kps", loader)
    assert await api._load_current_question_view(db, wrong()) == (current, [])
    stmt = db.execute.call_args.args[0]
    assert list(stmt.compile().params.values()) == [8]
    assert "question_version" not in str(stmt)
    assert loader.await_count == int(alive)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["confirm", "suggest", "read"])
async def test_missing_diagnosis_record_never_invalidates_or_commits(
    ports, monkeypatch, entry
):
    monkeypatch.setattr(api.svc, "get_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        api.error_diagnosis_service, "confirm_diagnosis", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        api.error_diagnosis_service,
        "request_ai_suggestion",
        AsyncMock(return_value=(None, False)),
    )
    with pytest.raises(HTTPException) as caught:
        if entry == "confirm":
            await api.confirm_wrong_error_diagnosis(
                4,
                SimpleNamespace(
                    primary_type="concept", secondary_types=[], diagnosis_id=None
                ),
                ports.db,
                ports.user,
            )
        elif entry == "suggest":
            await api.suggest_wrong_error_diagnosis(4, ports.db, ports.user)
        else:
            await api.get_wrong_error_diagnosis(4, ports.db, ports.user)
    assert caught.value.status_code == 404
    ports.db.commit.assert_not_awaited()
    api.cache.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_suggestion_preserves_queued_value_and_does_not_commit(
    ports, monkeypatch
):
    queued = object()
    monkeypatch.setattr(
        api.error_diagnosis_service,
        "request_ai_suggestion",
        AsyncMock(return_value=(SimpleNamespace(id=6), queued)),
    )
    result = await api.suggest_wrong_error_diagnosis(4, ports.db, ports.user)
    assert list(result) == ["queued", "diagnosis"]
    assert result["queued"] is queued and result["diagnosis"] == {"id": 6}
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_cache_failure_keeps_completed_service_result_but_stops_response(
    ports, monkeypatch
):
    operation = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(api.svc, "batch_operate", operation)
    failure = RuntimeError("cache failed")
    api.cache.delete.side_effect = [None, failure]
    with pytest.raises(RuntimeError) as caught:
        await api.batch_operate(
            SimpleNamespace(action=SimpleNamespace(value="remove_from_book"), ids=[4]),
            ports.db,
            ports.user,
        )
    assert caught.value is failure
    operation.assert_awaited_once()
    assert api.cache.delete.await_count == 2
    ports.db.commit.assert_not_awaited()

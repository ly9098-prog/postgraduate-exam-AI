"""Wrong-book date filters share China calendar bounds in list and task flow."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.wrong_questions import router
from app.core.database import get_db
from app.core.security import get_current_user
from app.services import wrong_question_service as svc
from tests.test_features.test_wrong_question_batch import (
    _add_user,
    _add_wq,
    _close_db,
    _make_db,
)


@pytest_asyncio.fixture
async def dated_book():
    engine, session, path = await _make_db()
    try:
        await _add_user(session, 1)
        await _add_user(session, 2)
        rows = []
        # China 2026-10-14 spans UTC [2026-10-13 16:00, 2026-10-14 16:00).
        for index, timestamp in enumerate(
            [
                datetime(2026, 10, 13, 15, 59, 59),
                datetime(2026, 10, 13, 16),
                datetime(2026, 10, 14, 15, 59, 59, 999999),
                datetime(2026, 10, 14, 16),
            ]
        ):
            rows.append(await _add_wq(session, 1, 101 + index, created_at=timestamp))
        await _add_wq(session, 2, 201, created_at=datetime(2026, 10, 14))
        await _add_wq(session, 1, 202, created_at=datetime(2026, 10, 14), is_active=False)
        yield session, rows
    finally:
        await _close_db(engine, session, path)


@pytest.mark.asyncio
async def test_inclusive_china_dates_apply_to_total_pagination_and_task_groups(dated_book):
    session, rows = dated_book
    params = {"date_from": date(2026, 10, 14), "date_to": date(2026, 10, 14)}
    items, total = await svc.list_wrong_enriched(session, 1, page_size=1, **params)
    next_items, next_total = await svc.list_wrong_enriched(session, 1, page=2, page_size=1, **params)
    assert total == next_total == 2
    expected = {rows[1].id, rows[2].id}
    assert {item["id"] for item in items + next_items} == expected
    flow = await svc.get_task_flow(session, 1, preview_size=10, **params)
    assert flow["summary"]["total_count"] == 2
    assert sum(group["total"] for group in flow["groups"]) == 2
    assert {item["id"] for group in flow["groups"] for item in group["items"]} == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "indices"),
    [
        ({}, [0, 1, 2, 3]),
        ({"date_from": date(2026, 10, 14)}, [1, 2, 3]),
        ({"date_to": date(2026, 10, 14)}, [0, 1, 2]),
        ({"date_from": date(2026, 10, 16), "date_to": date(2026, 10, 17)}, []),
    ],
)
async def test_optional_bounds_keep_unfiltered_behavior_and_empty_totals(dated_book, params, indices):
    session, rows = dated_book
    items, total = await svc.list_wrong_enriched(session, 1, **params)
    assert total == len(indices)
    assert {item["id"] for item in items} == {rows[index].id for index in indices}
    flow = await svc.get_task_flow(session, 1, preview_size=10, **params)
    assert flow["summary"]["total_count"] == len(indices)


@pytest.mark.asyncio
async def test_date_range_composes_with_existing_wrong_cause_filter(dated_book):
    session, rows = dated_book
    rows[1].error_type = "careless"
    await session.commit()
    params = {
        "date_from": date(2026, 10, 14),
        "date_to": date(2026, 10, 14),
        "error_type": "careless",
    }
    items, total = await svc.list_wrong_enriched(session, 1, **params)
    assert total == 1
    assert items[0]["id"] == rows[1].id
    flow = await svc.get_task_flow(session, 1, **params)
    assert flow["summary"]["total_count"] == 1


@pytest.fixture
def date_client(monkeypatch):
    db = AsyncMock()
    list_mock = AsyncMock(return_value=([], 0))
    flow_mock = AsyncMock(return_value={
        "summary": {"total_count": 0, "mastered_count": 0, "high_frequency_count": 0, "today_due_count": 0},
        "groups": [],
    })
    monkeypatch.setattr(svc, "list_wrong_enriched", list_mock)
    monkeypatch.setattr(svc, "get_task_flow", flow_mock)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        yield client, list_mock, flow_mock


@pytest.mark.parametrize("path", ["/api/v1/wrong-questions", "/api/v1/wrong-questions/task-flow"])
def test_api_forwards_calendar_dates_to_both_services(date_client, path):
    client, list_mock, flow_mock = date_client
    response = client.get(path, params={"date_from": "2026-10-01", "date_to": "2026-10-14"})
    assert response.status_code == 200
    call = flow_mock.call_args if path.endswith("task-flow") else list_mock.call_args
    assert call.kwargs["date_from"] == date(2026, 10, 1)
    assert call.kwargs["date_to"] == date(2026, 10, 14)


@pytest.mark.parametrize("path", ["/api/v1/wrong-questions", "/api/v1/wrong-questions/task-flow"])
@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-10-15", "date_to": "2026-10-14"},
        {"date_from": "2026-02-30"},
        {"date_to": "invalid"},
    ],
)
def test_api_rejects_reversed_and_invalid_dates_before_querying(date_client, path, params):
    client, list_mock, flow_mock = date_client
    response = client.get(path, params=params)
    assert response.status_code == 422
    list_mock.assert_not_awaited()
    flow_mock.assert_not_awaited()

"""Study-plan PUT contract used by the miniprogram save flow."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.study_plan import router
from app.core.database import get_db
from app.core.security import get_current_user
from app.services import study_plan_service

TODAY = date(2026, 10, 14)


@pytest.fixture
def plan_client(monkeypatch):
    db = AsyncMock()
    plan = SimpleNamespace(
        id=1,
        target_date=TODAY,
        daily_minutes=90,
        weekly_days=6,
        priority_mode="balanced",
        revision=1,
        is_active=True,
        created_at=datetime(2026, 10, 14),
        updated_at=datetime(2026, 10, 14),
    )
    get_plan = AsyncMock(return_value=plan)
    monkeypatch.setattr(study_plan_service, "_get_user_plan", get_plan)
    monkeypatch.setattr(study_plan_service, "shanghai_today", lambda: TODAY)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
    with TestClient(app) as client:
        yield client, db, plan, get_plan


@pytest.mark.parametrize("target_date", ["2026-10-14", "2026-12-20"])
def test_put_saves_today_or_future_target_with_miniprogram_payload(plan_client, target_date):
    client, db, plan, get_plan = plan_client
    payload = {
        "target_date": target_date,
        "daily_minutes": 240,
        "weekly_days": 7,
        "priority_mode": "exam",
    }

    response = client.put("/api/v1/study-plan", json=payload)

    assert response.status_code == 200
    assert {key: response.json()[key] for key in payload} == payload
    assert response.json()["revision"] == 2
    get_plan.assert_awaited_once_with(db, 7, lock=True)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(plan)


def test_put_rejects_expired_target_before_reading_or_writing_plan(plan_client):
    client, db, _, get_plan = plan_client

    response = client.put(
        "/api/v1/study-plan",
        json={"target_date": "2026-10-13", "daily_minutes": 90, "weekly_days": 6},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "目标日期不能早于今天"
    get_plan.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "invalid_field",
    [
        {"target_date": "2026-02-30"},
        {"target_date": "2027-02-29"},
        {"daily_minutes": 14},
        {"weekly_days": 8},
        {"priority_mode": "unknown"},
    ],
)
def test_put_keeps_schema_validation_for_invalid_plan_settings(plan_client, invalid_field):
    client, db, _, get_plan = plan_client
    payload = {
        "target_date": "2026-12-20",
        "daily_minutes": 90,
        "weekly_days": 6,
        "priority_mode": "balanced",
        **invalid_field,
    }

    response = client.put("/api/v1/study-plan", json=payload)

    assert response.status_code == 422
    get_plan.assert_not_awaited()
    db.commit.assert_not_awaited()

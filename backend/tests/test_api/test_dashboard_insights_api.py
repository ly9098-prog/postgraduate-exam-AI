"""Public insights protocol uses the current user's independent request context."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.stats import router
from app.core.database import get_db
from app.core.security import get_current_user
from app.services import dashboard_insights_service as svc


@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    db = object()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=17)
    payload = {
        name: None
        for name in (
            "today_quality",
            "weekly_consistency",
            "weak_topic_ranking",
            "repeat_wrong_analysis",
            "speed_accuracy",
            "new_vs_review",
            "input_output",
        )
    }
    payload["action_plan"] = {"data_available": True, "items": []}
    service = AsyncMock(return_value=payload)
    monkeypatch.setattr(svc, "get_dashboard_insights", service)
    with TestClient(app) as client:
        yield app, client, db, service, payload


def test_defaults_and_response_projection(api):
    _, client, db, service, payload = api
    response = client.get("/api/v1/stats/dashboard-insights")
    assert response.status_code == 200
    assert response.json() == payload
    service.assert_awaited_once_with(
        db, 17, days=7, include_subjects=True, include_topics=True
    )


def test_explicit_days_and_flags(api):
    _, client, db, service, _ = api
    response = client.get(
        "/api/v1/stats/dashboard-insights?days=90&include_subjects=false&include_topics=false"
    )
    assert response.status_code == 200
    service.assert_awaited_once_with(
        db, 17, days=90, include_subjects=False, include_topics=False
    )


@pytest.mark.parametrize("query", ["days=0", "days=91", "days=x", "include_topics=x"])
def test_invalid_query_never_calls_service(api, query):
    _, client, _, service, _ = api
    assert client.get("/api/v1/stats/dashboard-insights?" + query).status_code == 422
    service.assert_not_awaited()


def test_identity_dependency_rejection_never_calls_service(api):
    app, client, _, service, _ = api

    def reject():
        raise HTTPException(status_code=401, detail="test identity required")

    app.dependency_overrides[get_current_user] = reject
    assert client.get("/api/v1/stats/dashboard-insights").status_code == 401
    service.assert_not_awaited()

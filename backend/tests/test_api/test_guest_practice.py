from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import public_api_router
from app.core.cache import CacheUnavailableError
from app.core.database import get_db
from app.services import guest_rate_limit


@pytest.fixture
def client():
    application = FastAPI()
    application.include_router(public_api_router)
    database = AsyncMock()
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    empty.scalar.return_value = 0
    empty.all.return_value = []
    database.execute.return_value = empty
    application.dependency_overrides[get_db] = lambda: database
    with TestClient(application) as test_client:
        yield test_client, database


def test_guest_evaluation_rejects_forged_batch_before_database_access(client):
    test_client, database = client
    response = test_client.post(
        "/api/v1/guest/practice/evaluate",
        json={"batch_token": "forged", "answers": []},
    )
    assert response.status_code == 400
    database.execute.assert_not_called()


@pytest.mark.parametrize(("mode", "count", "status"), [
    ("sequential", 5, 422),
    ("smart", 5, 422),
    ("random", 7, 422),
])
def test_guest_question_endpoint_only_accepts_random_supported_counts(client, mode, count, status):
    test_client, database = client
    response = test_client.get(
        "/api/v1/guest/practice/questions",
        params={"subject_id": 1, "mode": mode, "count": count},
    )
    assert response.status_code == status
    database.execute.assert_not_called()


def test_anonymous_formula_reads_never_expose_personal_favorites(client):
    test_client, database = client
    response = test_client.get("/api/v1/formulas/catalog?favorite_only=true")
    assert response.status_code == 200
    assert response.json()["items"] == []

    favorites = test_client.get("/api/v1/formulas/favorites/list")
    assert favorites.status_code in (401, 403)


def test_guest_credentials_never_authenticate_formal_practice(client):
    test_client, database = client
    response = test_client.post(
        "/api/v1/practice/batch-submit",
        headers={"Authorization": "Bearer guest.invalid"},
        json={},
    )
    assert response.status_code == 401
    database.commit.assert_not_called()


@pytest.mark.parametrize("header", ["Bearer invalid", "Basic invalid", "Bearer", ""])
def test_invalid_optional_credentials_are_never_silently_anonymous(client, header):
    test_client, database = client
    response = test_client.get(
        "/api/v1/formulas/catalog", headers={"Authorization": header},
    )
    assert response.status_code == 401
    database.execute.assert_not_called()


@pytest.mark.parametrize("path", [
    "/api/v1/formulas/catalog",
    "/api/v1/formulas",
    "/api/v1/formulas/tags",
    "/api/v1/formulas/random/next",
    "/api/v1/guest/practice/subjects",
    "/api/v1/practice/subjects",
    "/api/v1/guest/practice/questions?subject_id=1",
])
def test_public_reads_do_not_require_identity(client, path):
    test_client, database = client
    response = test_client.get(path)
    assert response.status_code in (200, 404)
    database.add.assert_not_called()
    database.commit.assert_not_called()


@pytest.mark.parametrize(("counter", "status"), [(121, 429), (CacheUnavailableError(), 503)])
def test_guest_http_budget_rejects_before_content_reads(client, monkeypatch, counter, status):
    test_client, database = client
    mock = AsyncMock(
        side_effect=counter if isinstance(counter, Exception) else None,
        return_value=counter,
    )
    monkeypatch.setattr(guest_rate_limit.cache, "increment_strict", mock)
    response = test_client.get("/api/v1/guest/practice/subjects")
    assert response.status_code == status
    database.execute.assert_not_called()


def test_anonymous_subject_catalog_preserves_non_question_subjects(client, monkeypatch):
    from app.api.v1 import practice

    test_client, database = client
    tree = [{
        "subject_id": 1, "subject_name": "数学", "children": [
            {"subject_id": 5, "subject_name": "高数", "children": []},
            {"subject_id": 6, "subject_name": "线性代数", "children": []},
        ],
    }]
    loader = AsyncMock(return_value=tree)
    monkeypatch.setattr(practice.svc, "get_practice_subject_tree", loader)
    response = test_client.get("/api/v1/practice/subjects")
    assert response.status_code == 200
    assert response.json() == tree
    loader.assert_awaited_once_with(database)
    database.add.assert_not_called()
    database.commit.assert_not_called()


@pytest.mark.parametrize("header", ["Bearer invalid", "Basic invalid", "Bearer", ""])
def test_subject_catalog_rejects_invalid_supplied_identity(client, header):
    test_client, database = client
    response = test_client.get(
        "/api/v1/practice/subjects", headers={"Authorization": header},
    )
    assert response.status_code == 401
    database.execute.assert_not_called()

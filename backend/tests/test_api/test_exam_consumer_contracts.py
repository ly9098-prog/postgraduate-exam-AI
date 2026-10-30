"""Nine current exam contracts against an isolated SQLite service chain."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.exams import router
from app.core.database import get_db
from app.core.security import get_current_user
from tests.test_services.test_exam_attempt_semantics import _make_database, _seed


@pytest.mark.asyncio
async def test_nine_consumer_contracts_keep_revision_result_and_history(tmp_path):
    engine, factory = await _make_database(tmp_path)
    try:
        await _seed(factory)
        app = FastAPI()
        app.include_router(router)

        async def database():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            papers = await client.get("/api/v1/exams/papers")
            assert papers.status_code == 200
            assert papers.json()[0]["question_count"] == 2
            detail = await client.get("/api/v1/exams/papers/1")
            assert detail.status_code == 200
            assert detail.json()["total_choice_score"] == 5
            assert detail.json()["subject_distribution"][0]["question_count"] == 2
            started = await client.post(
                "/api/v1/exams/papers/1/attempts",
                json={"request_id": "consumer-start-1"},
            )
            assert started.status_code == 200
            attempt_id = started.json()["id"]
            url = f"/api/v1/exams/attempts/{attempt_id}"
            view = await client.get(url)
            assert view.status_code == 200
            questions = view.json()["questions"]
            assert [q["question_version_id"] for q in questions] == [1, 2]
            assert all("answer" not in q and "analysis" not in q for q in questions)
            saved = await client.patch(
                f"{url}/answers/1",
                json={
                    "selected_answer": "a",
                    "marked_for_review": True,
                    "used_time": 12,
                },
            )
            assert saved.status_code == 200
            assert saved.json()["answer"]["selected_answer"] == "A"
            early_result = await client.get(f"{url}/result")
            assert early_result.status_code == 409
            submitted = await client.post(
                f"{url}/submit",
                json={
                    "answers": [
                        {
                            "item_id": 2,
                            "selected_answer": "b",
                            "marked_for_review": False,
                            "used_time": 15,
                        }
                    ]
                },
            )
            assert submitted.status_code == 200
            snapshot = submitted.json()
            assert snapshot["correct_count"] == 2
            assert snapshot["choice_score"] == 5
            assert (await client.get(f"{url}/result")).json() == snapshot
            assert (await client.post(f"{url}/submit", json={})).json() == snapshot
            history = await client.get("/api/v1/exams/history")
            overview = await client.get(
                "/api/v1/exams/history/overview?limit=1&offset=0"
            )
            assert history.status_code == overview.status_code == 200
            assert history.json() == overview.json()["items"]
            assert history.json()[0]["attempt_id"] == attempt_id
            assert history.json()[0]["accuracy"] == 1
            assert overview.json()["summary"]["completed_count"] == 1
            next_attempt = await client.post(
                "/api/v1/exams/papers/1/attempts",
                json={"request_id": "consumer-start-2"},
            )
            assert next_attempt.status_code == 200
            new_id = next_attempt.json()["id"]
            assert new_id != attempt_id
            abandoned = await client.post(f"/api/v1/exams/attempts/{new_id}/abandon")
            assert abandoned.status_code == 200
            assert abandoned.json() == {"id": new_id, "status": "abandoned"}
    finally:
        await engine.dispose()

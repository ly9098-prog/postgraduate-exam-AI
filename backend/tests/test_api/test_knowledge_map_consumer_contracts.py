"""HTTP/schema wiring for the two current knowledge-map consumers."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.knowledge_map import router
from app.core.database import get_db
from app.core.security import get_current_user
from tests.test_services.test_knowledge_map_compatibility import _make_database, _seed


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["subjects", "points"])
async def test_current_consumer_get_serializes_real_isolated_service(tmp_path, resource):
    engine, factory = await _make_database(tmp_path)
    try:
        ids = await _seed(factory)
        app = FastAPI()
        app.include_router(router)

        async def database():
            async with factory() as db:
                yield db
                assert not db.new and not db.dirty and not db.deleted

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=9)
        point_id = ids["ds"] if resource == "subjects" else 1
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/v1/knowledge-map/{resource}/{point_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "exam408"
        assert data["syllabus_version"]["code"] == "active-2026"
        if resource == "subjects":
            assert data["subject"]["subject_id"] == ids["ds"]
            assert [node["knowledge_point_id"] for node in data["nodes"]] == [1, 2]
            assert data["nodes"][0]["direct_child_count"] == 1
            assert data["nodes"][1]["trainable_question_count"] == 1
        else:
            assert data["knowledge_point_id"] == 1
            assert data["direct_children"][0]["knowledge_point_id"] == 2
            assert data["practice_route_params"]["include_descendants"] == 1
            assert data["practice_route_params"]["subject_id"] == ids["ds"]
            assert data["recent_answers"] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resource", "message"),
    [
        ("subjects", "408 科目不存在、已停用或不在当前产品范围"),
        ("points", "知识点不存在、已停用或不属于当前 408 范围"),
    ],
)
async def test_missing_or_invalid_consumer_id_keeps_http_contract(tmp_path, resource, message):
    engine, factory = await _make_database(tmp_path)
    try:
        await _seed(factory)
        app = FastAPI()
        app.include_router(router)

        async def database():
            async with factory() as db:
                yield db

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=9)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            missing = await client.get(f"/api/v1/knowledge-map/{resource}/99999")
            invalid = await client.get(f"/api/v1/knowledge-map/{resource}/not-an-integer")
        assert missing.status_code == 404
        assert missing.json() == {"detail": message}
        assert invalid.status_code == 422
        assert invalid.json()["detail"][0]["loc"][0] == "path"
    finally:
        await engine.dispose()

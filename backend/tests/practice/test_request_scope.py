"""Regression checks for practice subject and knowledge scope orchestration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.practice import request_scope
from app.services.practice.request_filters import PracticeRequestFilterError


@pytest.mark.asyncio
async def test_subject_scope_rejects_missing_subject(monkeypatch):
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_subject_id_to_code",
        AsyncMock(return_value=None),
    )
    with pytest.raises(request_scope.PracticeScopeNotFoundError, match="不存在"):
        await request_scope.resolve_subject_scope(
            SimpleNamespace(), subject_id=9, include_children=False, mode="random"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("include_children", [True, False])
async def test_subject_scope_keeps_sequential_leaf_boundary(
    monkeypatch, include_children
):
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_subject_id_to_code",
        AsyncMock(return_value=("ds", "数据结构")),
    )
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_practice_subject_scope",
        AsyncMock(return_value=(True, [1, 2])),
    )
    with pytest.raises(PracticeRequestFilterError, match="顺序练习"):
        await request_scope.resolve_subject_scope(
            SimpleNamespace(),
            subject_id=1,
            include_children=include_children,
            mode="sequential",
        )


@pytest.mark.asyncio
async def test_disabled_subject_fails_before_sequential_mode_validation(monkeypatch):
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_subject_id_to_code",
        AsyncMock(return_value=("cs", "计算机")),
    )
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_practice_subject_scope",
        AsyncMock(return_value=(True, [])),
    )
    with pytest.raises(request_scope.PracticeScopeNotFoundError, match="停用"):
        await request_scope.resolve_subject_scope(
            SimpleNamespace(),
            subject_id=1,
            include_children=True,
            mode="sequential",
        )


@pytest.mark.asyncio
async def test_subject_scope_returns_stable_scope_data(monkeypatch):
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_subject_id_to_code",
        AsyncMock(return_value=("ds", "数据结构")),
    )
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_practice_subject_scope",
        AsyncMock(return_value=(False, [2])),
    )
    db = SimpleNamespace()
    result = await request_scope.resolve_subject_scope(
        db, subject_id=2, include_children=False, mode="random"
    )
    assert result.code == "ds"
    assert result.name == "数据结构"
    assert result.subject_ids == [2]
    assert result.has_enabled_children is False
    request_scope.practice_service.resolve_subject_id_to_code.assert_awaited_once_with(
        db, 2
    )
    request_scope.practice_service.resolve_practice_subject_scope.assert_awaited_once_with(
        db,
        2,
        False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("include_descendants", [False, True])
async def test_knowledge_scope_keeps_canonical_and_legacy_filters(
    monkeypatch, include_descendants
):
    snapshot = {"root_name": "导数", "knowledge_point_ids": [4, 5]}
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_practice_knowledge_scope",
        AsyncMock(return_value=snapshot),
    )
    db = SimpleNamespace()
    result = await request_scope.resolve_knowledge_filter(
        db,
        knowledge_point=None,
        knowledge_point_id=4,
        include_descendants=include_descendants,
        subject_ids=[2],
    )
    assert result.point_ids == [4, 5]
    assert result.point_ids is not snapshot["knowledge_point_ids"]
    assert result.names == (None if include_descendants else ["导数"])
    assert result.scope is snapshot
    request_scope.practice_service.resolve_practice_knowledge_scope.assert_awaited_once_with(
        db,
        knowledge_point_id=4,
        subject_ids=[2],
        include_descendants=include_descendants,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,expected", [(None, None), (" , ", []), ("导数", ["导数"])]
)
async def test_legacy_names_do_not_query_canonical_scope(monkeypatch, name, expected):
    resolver = AsyncMock()
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_practice_knowledge_scope",
        resolver,
    )
    result = await request_scope.resolve_knowledge_filter(
        SimpleNamespace(),
        knowledge_point=name,
        knowledge_point_id=None,
        include_descendants=False,
        subject_ids=[2],
    )
    assert result.names == expected
    assert result.scope is None
    assert result.point_ids is None
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_scope_rejects_missing_canonical_scope(monkeypatch):
    monkeypatch.setattr(
        request_scope.practice_service,
        "resolve_practice_knowledge_scope",
        AsyncMock(return_value=None),
    )
    with pytest.raises(request_scope.PracticeScopeNotFoundError, match="知识点"):
        await request_scope.resolve_knowledge_filter(
            SimpleNamespace(),
            knowledge_point=None,
            knowledge_point_id=4,
            include_descendants=True,
            subject_ids=[2],
        )

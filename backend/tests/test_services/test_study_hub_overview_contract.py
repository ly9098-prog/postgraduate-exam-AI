"""Contracts for the study hub overview aggregation and decision ordering."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.core.subject_scope import EXAM408_CORE_CODES, EXAM408_ROOT_CODE
from app.services import study_hub_service as hub

PLAN_DATE = date(2026, 10, 28)


class Ports:
    def __init__(self):
        self.events: list[str] = []
        self.scope = (None, [])
        self.review: dict = {}
        self.counts = (0, 0)
        self.mastery: list = []
        self.chapter = None
        self.weak = None
        self.hard: list = []
        self.path = None
        self.completed: set[str] = set()
        self.tokens: list[tuple] = []
        self.today_calls = 0
        self.core_ids: list[int] = []


@pytest.fixture
def ports(monkeypatch):
    ports = Ports()

    async def fake_scope(db):
        ports.events.append("scope")
        return ports.scope

    async def fake_review(db, user_id):
        ports.events.append("review")
        return ports.review

    async def fake_counts(db, user_id, core_subject_ids):
        ports.events.append("counts")
        ports.core_ids = list(core_subject_ids)
        return ports.counts

    async def fake_mastery(db, user_id, core_subjects):
        ports.events.append("mastery")
        return ports.mastery

    async def fake_chapter(db, user_id, subject_mastery):
        ports.events.append("chapter")
        return ports.chapter

    async def fake_weak(db, user_id, core_subject_ids):
        ports.events.append("weak")
        return ports.weak

    async def fake_hard(db, user_id, core_subject_ids):
        ports.events.append("hard")
        return ports.hard

    async def fake_path(db, user_id, core_subject_ids):
        ports.events.append("path")
        return ports.path

    async def fake_completed(db, *, user_id, plan_date):
        ports.events.append("completed")
        return set(ports.completed)

    def fake_token(task, *, user_id, plan_date):
        ports.tokens.append((task.get("key"), user_id, plan_date))

    class FakeReviewScheduler:
        async def get_today_review_overview(self, db, user_id):
            ports.events.append("review_today")
            return ports.review

    def fake_today():
        ports.today_calls += 1
        return PLAN_DATE

    monkeypatch.setattr(hub, "_load_subject_scope", fake_scope)
    monkeypatch.setattr(hub, "review_scheduler", FakeReviewScheduler())
    monkeypatch.setattr(hub, "_load_408_practice_counts", fake_counts)
    monkeypatch.setattr(hub, "_build_subject_mastery", fake_mastery)
    monkeypatch.setattr(hub, "_pick_chapter_recommendation", fake_chapter)
    monkeypatch.setattr(hub, "_pick_weak_point", fake_weak)
    monkeypatch.setattr(hub, "_pick_hard_questions", fake_hard)
    monkeypatch.setattr(hub, "_pick_path_prerequisite", fake_path)
    monkeypatch.setattr(hub, "_load_completed_plan_task_keys", fake_completed)
    monkeypatch.setattr(hub, "_attach_plan_token", fake_token)
    monkeypatch.setattr(hub, "shanghai_today", fake_today)
    return ports


def make_scope(core_count=4):
    root = SimpleNamespace(id=7, code=EXAM408_ROOT_CODE, name="计算机学科专业基础综合")
    cores = [
        SimpleNamespace(id=101 + index, code=code, name=f"科目{code}")
        for index, code in enumerate(EXAM408_CORE_CODES[:core_count])
    ]
    return root, cores


def make_weak_point(**overrides):
    data = {
        "subject_id": 101,
        "subject_code": "A",
        "subject_name": "数据结构",
        "knowledge_point_id": 501,
        "knowledge_point_name": "二叉树遍历",
        "mastery_score": 62.4,
        "attempt_count": 6,
        "recent_wrong_count": 3,
        "available_question_count": 12,
    }
    data.update(overrides)
    return data


def make_path(**overrides):
    data = {
        "subject_id": 102,
        "subject_code": "B",
        "subject_name": "计算机组成原理",
        "knowledge_point_id": 601,
        "knowledge_point_name": "浮点数表示",
        "target_knowledge_point_id": 602,
        "target_knowledge_point_name": "浮点运算",
        "mastery_score": 48.6,
        "available_question_count": 9,
    }
    data.update(overrides)
    return data


def tasks_by_key(result):
    return {task["key"]: task for task in result["tasks"]}


@pytest.mark.asyncio
async def test_scope_not_ready_returns_fallback_without_loading_data(ports):
    ports.scope = (None, [])

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    assert ports.events == ["scope"]
    assert ports.today_calls == 1
    assert result["date"] == PLAN_DATE.isoformat()
    assert result["scope"] == EXAM408_ROOT_CODE
    assert result["scope_ready"] is False
    assert result["fallback_used"] is True
    assert result["today_question_count"] == 0
    assert result["total_practice_count"] == 0
    assert result["review"] == {}
    assert result["subject_mastery"] == []
    assert result["tasks"] == [result["primary_task"]]
    task = result["primary_task"]
    assert task == {
        "key": "scope-not-ready",
        "task_type": "smart_practice",
        "priority": 1,
        "title": "科目配置需要检查",
        "reason": "未找到完整的计算机专业课科目树，请先完成科目治理后再开始智能学习。",
        "action_label": "查看刷题入口",
        "route": "practice",
        "route_params": {},
        "estimated_question_count": 0,
        "estimated_minutes": 0,
    }


@pytest.mark.asyncio
async def test_incomplete_core_subjects_also_use_fallback(ports):
    ports.scope = make_scope(core_count=3)

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    assert result["scope_ready"] is False
    assert ports.events == ["scope"]


@pytest.mark.asyncio
async def test_new_user_gets_single_smart_fallback_without_chapter_probe(ports):
    ports.scope = make_scope()
    ports.counts = (0, 0)
    ports.review = {}

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    assert ports.events == [
        "scope",
        "review_today",
        "counts",
        "mastery",
        "weak",
        "hard",
        "path",
        "completed",
    ]
    assert ports.core_ids == [101, 102, 103, 104]
    assert ports.tokens == [("practice:fallback", 3, PLAN_DATE.isoformat())]
    assert len(result["tasks"]) == 1
    task = result["tasks"][0]
    assert result["primary_task"] is task
    assert task["key"] == "practice:fallback"
    assert task["task_type"] == "smart_practice"
    assert task["priority"] == 1
    assert task["title"] == "完成第一组练习"
    assert (
        task["reason"] == "当前学习数据还不足，先完成一组四科练习建立个性化推荐基线。"
    )
    assert task["action_label"] == "开始练习"
    assert task["route"] == "practice"
    assert task["route_params"] == {
        "subject_id": 7,
        "mode": "random",
        "count": 10,
        "autostart": 1,
        "source": "study_hub",
    }
    assert task["estimated_question_count"] == 10
    assert task["estimated_minutes"] == hub._minutes_for_questions(10)
    assert task["subject_id"] == 7
    assert task["subject_code"] == EXAM408_ROOT_CODE
    assert task["subject_name"] == "计算机学科专业基础综合"
    assert task["completed_today"] is False
    assert result["fallback_used"] is True
    assert result["scope_ready"] is True
    assert result["recommendation_limit"] == 3
    assert result["recommended_task_count"] == 1
    assert result["completed_recommendation_count"] == 0
    assert result["review"] == {
        "due_count": 0,
        "completed_count": 0,
        "remaining_count": 0,
        "overdue_count": 0,
        "estimated_minutes": 0,
    }
    assert result["subject_mastery"] == []


@pytest.mark.asyncio
async def test_review_task_uses_overdue_copy_and_summary_counters(ports):
    ports.scope = make_scope()
    ports.counts = (40, 9)
    ports.review = {
        "today_remaining_count": 5,
        "today_overdue_count": 2,
        "today_due_count": 14,
        "today_completed_count": 9,
        "estimated_minutes": 21,
    }

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    task = tasks_by_key(result)["review:due"]
    assert task["task_type"] == "review"
    assert task["title"] == "先完成 5 道到期复习"
    assert task["reason"] == "其中 2 道已经逾期，先处理可避免复习债继续累积。"
    assert task["action_label"] == "开始今日复习"
    assert task["route"] == "review_today"
    assert task["route_params"] == {}
    assert task["estimated_question_count"] == 5
    assert task["estimated_minutes"] == 21
    assert task["priority"] == 1
    assert result["review"] == {
        "due_count": 14,
        "completed_count": 9,
        "remaining_count": 5,
        "overdue_count": 2,
        "estimated_minutes": 21,
    }
    assert result["today_question_count"] == 9
    assert result["total_practice_count"] == 40
    assert result["fallback_used"] is False
    assert result["recommended_task_count"] == 2


@pytest.mark.asyncio
async def test_review_task_uses_window_copy_without_overdue(ports):
    ports.scope = make_scope()
    ports.counts = (40, 9)
    ports.review = {"today_remaining_count": 4, "today_overdue_count": 0}

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    task = tasks_by_key(result)["review:due"]
    assert task["reason"] == "这些题已经进入最佳复习窗口，优先巩固比继续加新题更划算。"
    assert task["estimated_minutes"] == 0


@pytest.mark.asyncio
async def test_chapter_task_is_probed_only_after_existing_practice(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.chapter = {
        "key": "chapter:7:12",
        "task_type": "knowledge_chapter",
        "priority": 0,
        "title": "推进「数组与矩阵」",
        "subject_id": 101,
    }

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    assert ports.events.index("chapter") == ports.events.index("mastery") + 1
    task = tasks_by_key(result)["chapter:7:12"]
    assert task["completed_today"] is False
    assert task["priority"] == 1
    assert ports.tokens == [
        ("chapter:7:12", 3, PLAN_DATE.isoformat()),
        ("practice:smart", 3, PLAN_DATE.isoformat()),
    ]


@pytest.mark.asyncio
async def test_weak_point_skipped_when_chapter_shares_subject(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.chapter = {
        "key": "chapter:7:12",
        "task_type": "knowledge_chapter",
        "subject_id": 101,
    }
    ports.weak = make_weak_point(subject_id=101)

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    assert not [key for key in tasks_by_key(result) if key.startswith("weak:")]


@pytest.mark.asyncio
async def test_weak_task_uses_recent_wrong_copy_and_allow_repeat(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.weak = make_weak_point()

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    task = tasks_by_key(result)["weak:501"]
    assert task["task_type"] == "weakness"
    assert task["title"] == "强化「二叉树遍历」"
    assert task["reason"] == "「二叉树遍历」近期重复错误 3 次，当前掌握度约 62 分。"
    assert task["action_label"] == "开始弱项强化"
    assert task["route_params"]["knowledge_point_id"] == 501
    assert task["route_params"]["include_children"] == 1
    assert "include_descendants" not in task["route_params"]
    assert task["route_params"]["allow_repeat"] == 1
    assert task["estimated_question_count"] == 8
    assert task["estimated_minutes"] == hub._minutes_for_questions(8)
    assert task["subject_id"] == 101
    assert task["subject_code"] == "A"
    assert task["subject_name"] == "数据结构"
    assert task["knowledge_point_id"] == 501
    assert task["knowledge_point_name"] == "二叉树遍历"


@pytest.mark.asyncio
async def test_weak_task_uses_attempt_copy_below_two_recent_wrong(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.weak = make_weak_point(
        recent_wrong_count=1, attempt_count=4, available_question_count=20
    )

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    task = tasks_by_key(result)["weak:501"]
    assert task["reason"] == "已练 4 次，当前掌握度约 62 分，适合做一轮小范围强化。"
    assert task["estimated_question_count"] == 8


@pytest.mark.asyncio
async def test_hard_task_reason_and_question_ids(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.hard = [
        {"question_id": 91, "wrong_count": 4},
        {"question_id": 92, "wrong_count": 0},
    ]

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    task = tasks_by_key(result)["hard:top"]
    assert task["task_type"] == "hard_questions"
    assert task["title"] == "重练 2 道个人难题"
    assert task["reason"] == "系统识别出 2 道个人高难题，其中最高已错 4 次。"
    assert task["action_label"] == "开始困难题重练"
    assert task["route_params"]["question_ids"] == "91,92"
    assert task["route_params"]["subject_id"] == 7
    assert task["question_ids"] == [91, 92]
    assert task["estimated_question_count"] == 2
    assert task["estimated_minutes"] == hub._minutes_for_questions(
        2, per_question_sec=120
    )


@pytest.mark.asyncio
async def test_hard_task_reason_without_wrong_history(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.hard = [{"question_id": 91, "wrong_count": 0}]

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    task = tasks_by_key(result)["hard:top"]
    assert task["reason"] == "系统识别出 1 道个人高难题，适合重新检验解题稳定性。"


@pytest.mark.asyncio
async def test_path_task_skipped_when_knowledge_point_already_used(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.weak = make_weak_point()
    ports.path = make_path(knowledge_point_id=501)

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    assert not [key for key in tasks_by_key(result) if key.startswith("path:")]


@pytest.mark.asyncio
async def test_path_task_uses_target_name_and_caps_count(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.path = make_path(
        target_knowledge_point_name=None, available_question_count=30
    )

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    task = tasks_by_key(result)["path:601:602"]
    assert task["task_type"] == "knowledge_path"
    assert task["title"] == "先补「浮点数表示」"
    assert (
        task["reason"]
        == "它是「后续知识点」的前置知识，当前掌握度约 49 分；先补前置再推进更稳。"
    )
    assert task["action_label"] == "继续知识路径"
    assert task["route_params"]["knowledge_point"] == "浮点数表示"
    assert task["route_params"]["allow_repeat"] == 1
    assert "knowledge_point_id" not in task["route_params"]
    assert task["estimated_question_count"] == 6
    assert task["subject_id"] == 102
    assert task["knowledge_point_id"] == 601
    assert task["knowledge_point_name"] == "浮点数表示"


@pytest.mark.asyncio
async def test_completed_tasks_are_demoted_then_capped_and_numbered(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.review = {"today_remaining_count": 3}
    ports.chapter = {
        "key": "chapter:7:12",
        "task_type": "knowledge_chapter",
        "subject_id": 103,
    }
    ports.weak = make_weak_point(recent_wrong_count=0)
    ports.hard = [{"question_id": 91, "wrong_count": 1}]
    ports.path = make_path()
    ports.completed = {"review:due", "chapter:7:12"}

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    keys = [task["key"] for task in result["tasks"]]
    assert keys == ["weak:501", "hard:top", "path:601:602"]
    assert [task["priority"] for task in result["tasks"]] == [1, 2, 3]
    assert result["recommended_task_count"] == 3
    assert result["completed_recommendation_count"] == 2
    assert result["primary_task"] is result["tasks"][0]
    assert ports.tokens == [
        ("weak:501", 3, PLAN_DATE.isoformat()),
        ("hard:top", 3, PLAN_DATE.isoformat()),
        ("path:601:602", 3, PLAN_DATE.isoformat()),
    ]
    assert [task["completed_today"] for task in result["tasks"]] == [
        False,
        False,
        False,
    ]


@pytest.mark.asyncio
async def test_completed_only_keys_stay_visible_after_pending_tasks(ports):
    ports.scope = make_scope()
    ports.counts = (12, 0)
    ports.review = {"today_remaining_count": 3}
    ports.completed = {"review:due"}

    result = await hub.get_study_hub_overview(db=object(), user_id=3)

    keys = [task["key"] for task in result["tasks"]]
    assert keys == ["practice:smart", "review:due"]
    assert [task["completed_today"] for task in result["tasks"]] == [False, True]
    assert [task["priority"] for task in result["tasks"]] == [1, 2]
    assert ports.tokens == [
        ("practice:smart", 3, PLAN_DATE.isoformat()),
        ("review:due", 3, PLAN_DATE.isoformat()),
    ]

from app.services.study_hub_plan_token import (
    issue_plan_task_token,
    validate_plan_task_token,
)


def test_plan_token_round_trip_matches_exact_practice_request():
    token = issue_plan_task_token(
        user_id=7,
        plan_date="2026-09-10",
        task_key="chapter:7:12",
        subject_id=7,
        mode="random",
        count=10,
        knowledge_point_id=12,
        include_descendants=True,
    )

    context = validate_plan_task_token(
        token,
        user_id=7,
        subject_id=7,
        mode="random",
        count=10,
        knowledge_point_id=12,
        include_descendants=True,
    )

    assert context == {
        "v": 1,
        "source": "home_today_plan",
        "plan_date": "2026-09-10",
        "task_key": "chapter:7:12",
    }


def test_plan_token_mismatch_drops_attribution_without_relabeling():
    token = issue_plan_task_token(
        user_id=7,
        plan_date="2026-09-10",
        task_key="weak:159",
        subject_id=7,
        mode="random",
        count=8,
        knowledge_point_id=159,
    )

    # User changed count on the setup page: normal practice remains legal, but
    # this token must no longer count as completing the original recommendation.
    assert validate_plan_task_token(
        token,
        user_id=7,
        subject_id=7,
        mode="random",
        count=10,
        knowledge_point_id=159,
    ) is None


def test_plan_token_binds_targeted_question_set():
    token = issue_plan_task_token(
        user_id=7,
        plan_date="2026-09-10",
        task_key="hard:top",
        subject_id=1,
        mode="random",
        count=3,
        question_ids="11,12,13",
    )

    assert validate_plan_task_token(
        token,
        user_id=7,
        subject_id=1,
        mode="random",
        count=3,
        question_ids="11,12,14",
    ) is None

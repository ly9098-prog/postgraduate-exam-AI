"""Pin recommendation wording, precedence and lazy knowledge lookups."""

import pytest

from app.services.practice import smart_scoring


def reason(codes, *, ids=None, names=None, **kwargs):
    return smart_scoring._build_smart_recommendation_reason(
        codes,
        [1] if ids is None else ids,
        {} if names is None else names,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ([], "根据你的近期答题表现和知识掌握情况推荐。"),
        (["diversity"], "为避免重复刷同类题，这道题用于补充近期练习的知识覆盖。"),
        (["long_unpracticed"], "这个知识点已有一段时间没有练习，适合现在做一次巩固。"),
        (
            ["long_unpracticed", "diversity"],
            "这个知识点已有一段时间没有练习，同时近期覆盖较少，适合现在做一次巩固。",
        ),
        (["new_question"], "这是一道尚未练过的新题，用来检验当前掌握情况。"),
        (
            ["new_question", "diversity"],
            "这是一道尚未练过的新题，同时用于补充近期练习的知识覆盖，检验当前掌握情况。",
        ),
        (
            ["wrong_history"],
            "你之前在这类题目上出现过错误，建议再次练习确认是否已经掌握。",
        ),
        (
            ["wrong_history", "long_unpracticed"],
            "你之前在这类题目上出现过错误，而且已有一段时间没有练习，建议现在重做确认是否已经掌握。",
        ),
        (
            ["due_review", "new_question"],
            "这道题已进入复习窗口，现在练习有助于巩固记忆。",
        ),
        (
            ["due_review", "wrong_history", "weak_kp"],
            "这道题已进入复习窗口，而且你之前在这类题目上出现过错误，现在重做有助于巩固记忆并确认是否已经掌握。",
        ),
        (
            ["weak_kp", "observed_weak", "wrong_history"],
            "你最近在这类知识点上的掌握度较低，而且之前在相关题目上出现过错误，建议继续巩固。",
        ),
        (
            ["weak_kp", "new_question", "wrong_history"],
            "你最近在这类知识点上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。",
        ),
        (
            ["observed_weak", "wrong_history"],
            "你近期在相关知识点上的练习表现有待提升，建议继续巩固并确认掌握情况。",
        ),
        (["path_ready"], "根据你的近期答题表现和知识掌握情况推荐。"),
    ],
)
def test_wording_and_precedence(codes, expected):
    assert reason(codes) == expected


@pytest.mark.parametrize(
    ("new", "expected"),
    [
        (
            False,
            "「基础」是「目标」的前置知识，目前掌握数据较少，这道题可用于快速确认基础是否扎实。",
        ),
        (
            True,
            "「基础」是「目标」的前置知识，目前掌握数据较少，这道题可用于快速确认基础是否扎实，并通过一道尚未练过的新题减少熟题记忆带来的干扰。",
        ),
    ],
)
def test_graph_unknown_precedes_review_and_uses_first_candidate(new, expected):
    codes = ["due_review", "weak_kp"] + (["new_question"] if new else [])
    assert (
        reason(
            codes,
            ids=[2, 1],
            names={1: "忽略"},
            graph_candidates={
                2: {"name": "基础", "origin_name": "目标"},
                1: {"confirmed_gap": True},
            },
        )
        == expected
    )


def test_confirmed_graph_gap_and_blocker_append_identical_new_context():
    suffix = " 同时推荐一道尚未练过的新题，用来检验当前掌握情况。"
    assert (
        reason(
            ["new_question"],
            names={1: "基础"},
            graph_candidates={1: {"confirmed_gap": True}},
        )
        == "你在「目标知识点」上的掌握较弱，而「基础」是它的重要前置知识，建议先巩固「基础」。"
        + suffix
    )
    assert (
        reason(
            ["path_ready", "new_question"],
            blocked_kps={1: [{}, {"name": "忽略"}]},
        )
        == "「当前知识点」仍需巩固，同时「前置知识」这一前置知识也较薄弱，建议结合练习。"
        + suffix
    )


def test_named_weakness_and_ready_choose_first_nonempty_name():
    assert (
        reason(
            ["weak_kp", "new_question"],
            ids=[2, 1],
            names={2: "", 1: "基础"},
        )
        == "你最近在「基础」上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。"
    )
    assert (
        reason(
            ["path_ready", "new_question"],
            names={1: "基础"},
        )
        == "相关前置知识已经基本具备，可以继续巩固「基础」；这道新题可用于检验能否顺利推进。"
    )


def test_observed_name_uses_live_port_lazily_with_original_objects(monkeypatch):
    calls = []
    ids, mastery, observations = [1, 2], {2: (20, 0)}, {2: (2, 2)}

    def observed(received_ids, received_mastery, received_observations):
        assert received_ids is ids
        assert received_mastery is mastery
        assert received_observations is observations
        calls.append("observed")
        return [2]

    monkeypatch.setattr(smart_scoring, "_get_observed_weak_kp_ids", observed)
    kwargs = dict(
        ids=ids,
        names={1: "首个", 2: "薄弱"},
        kp_mastery=mastery,
        kp_observations=observations,
    )
    assert reason(["observed_weak", "wrong_history"], **kwargs) == (
        "你近期在「薄弱」上的练习表现有待提升，而且之前在相关题目上出现过错误，建议继续巩固并确认掌握情况。"
    )
    assert calls == ["observed"]
    reason(["due_review", "observed_weak"], **kwargs)
    assert calls == ["observed"]


def test_observed_name_falls_back_to_regular_name_and_higher_rules_skip_port(
    monkeypatch,
):
    calls = []

    def observed(*args):
        calls.append(args)
        return [2]

    monkeypatch.setattr(smart_scoring, "_get_observed_weak_kp_ids", observed)
    assert reason(["observed_weak"], names={1: "普通"}) == (
        "你近期在「普通」上的练习表现有待提升，这道题适合继续巩固并确认掌握情况。"
    )
    assert len(calls) == 1
    reason(["weak_kp", "observed_weak"])
    reason(["observed_weak"], graph_candidates={1: {"confirmed_gap": True}})
    assert len(calls) == 1

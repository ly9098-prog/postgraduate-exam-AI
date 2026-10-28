"""Pure growth-profile projections for learning statistics."""

from __future__ import annotations

from typing import Any


def build_growth_profile(overview: dict[str, Any]) -> dict[str, Any]:
    """Build experience, level, streak copy and badge progress from overview data."""
    total_q = overview["total_questions"]
    accuracy = overview["accuracy"]
    streak = overview["consecutive_days"]
    mastered = overview["mastered_count"]
    today_q = overview["today_questions"]
    overview["due_review_count"]

    total_exp = total_q * 10 + mastered * 20 + streak * 5
    if accuracy >= 0.7 and total_q >= 10:
        total_exp += int(total_q * accuracy * 5)

    level_low, level_high, level, level_title = _current_level(total_exp)
    level_pct, exp_current, exp_to_next = _level_progress(
        total_exp, level_low, level_high
    )
    return {
        "total_exp": total_exp,
        "level": level,
        "level_title": level_title,
        "level_progress_pct": level_pct,
        "exp_current": exp_current,
        "exp_to_next": exp_to_next,
        "streak_days": streak,
        "streak_title": _streak_title(streak),
        "daily_boost": _daily_boost(today_q, total_q, streak),
        "badges": _build_badges(total_q, streak, mastered, accuracy),
    }


def _current_level(total_exp: int) -> tuple[int, int | None, int, str]:
    levels = [
        (0, 200, 1, "Lv1 起步"),
        (200, 600, 2, "Lv2 坚持者"),
        (600, 1500, 3, "Lv3 刷题达人"),
        (1500, 3500, 4, "Lv4 高效进阶"),
        (3500, None, 5, "Lv5 上岸冲刺"),
    ]
    current = levels[0]
    for level_low, level_high, level, title in levels:
        if total_exp >= level_low:
            current = (level_low, level_high, level, title)
    return current


def _level_progress(
    total_exp: int, level_low: int, level_high: int | None
) -> tuple[int, int, int]:
    if level_high is None:
        return 100, total_exp - level_low, 0
    return (
        min(100, round((total_exp - level_low) / (level_high - level_low) * 100)),
        total_exp - level_low,
        level_high - level_low,
    )


def _streak_title(streak: int) -> str:
    if streak >= 30:
        return "连续学习 30 天以上，习惯已成"
    if streak >= 15:
        return "连续学习 15 天，节奏渐稳"
    if streak >= 7:
        return "连续学习 7 天，势头正盛"
    if streak > 0:
        return f"连续学习 {streak} 天，继续加油"
    return "开始今天的学习，点亮第一天"


def _daily_boost(today_q: int, total_q: int, streak: int) -> str:
    if today_q > 0 and total_q > 0:
        return f"今日已练 {today_q} 题，连续 {streak} 天，累计 {total_q} 题"
    if total_q > 0:
        return f"累计 {total_q} 题，连续 {streak} 天，今日本站首练"
    return "完成第一道题，开启成长之旅"


def _build_badges(
    total_q: int, streak: int, mastered: int, accuracy: float
) -> list[dict[str, Any]]:
    return [
        *_first_learn_and_streak_badges(total_q, streak),
        *_question_count_badges(total_q),
        _accuracy_badge(total_q, accuracy),
        *_mastery_badges(mastered),
    ]


def _first_learn_and_streak_badges(total_q: int, streak: int) -> list[dict[str, Any]]:
    return [
        _badge(
            "first_learn",
            "首次学习",
            "完成第一道题",
            total_q > 0,
            100 if total_q > 0 else 0,
            "已解锁" if total_q > 0 else "0/1",
        ),
        _badge(
            "streak_7",
            "连续7天",
            "保持一周学习节奏",
            streak >= 7,
            min(100, round(streak / 7 * 100)),
            f"{min(streak, 7)}/7天",
        ),
        _badge(
            "streak_30",
            "连续30天",
            "形成长期学习习惯",
            streak >= 30,
            min(100, round(streak / 30 * 100)),
            f"{min(streak, 30)}/30天",
        ),
    ]


def _question_count_badges(total_q: int) -> list[dict[str, Any]]:
    return [
        _badge(
            "hundred",
            "百题积累",
            "累计完成100题",
            total_q >= 100,
            min(100, round(total_q / 100 * 100)),
            f"{min(total_q, 100)}/100题",
        ),
        _badge(
            "five_hundred",
            "500题达人",
            "累计完成500题",
            total_q >= 500,
            min(100, round(total_q / 500 * 100)),
            f"{min(total_q, 500)}/500题",
        ),
        _badge(
            "thousand",
            "千题斩",
            "累计完成1000题",
            total_q >= 1000,
            min(100, round(total_q / 1000 * 100)),
            f"{min(total_q, 1000)}/1000题",
        ),
    ]


def _accuracy_badge(total_q: int, accuracy: float) -> dict[str, Any]:
    return _badge(
        "accuracy_90",
        "正确率90%",
        "稳定高质量输出",
        accuracy >= 0.9 and total_q >= 30,
        min(100, round(accuracy / 0.9 * 100)) if total_q >= 10 else 0,
        f"{round(accuracy * 100)}%",
    )


def _mastery_badges(mastered: int) -> list[dict[str, Any]]:
    return [
        _badge(
            "master_50",
            "掌握50题",
            "错题转化为能力",
            mastered >= 50,
            min(100, round(mastered / 50 * 100)),
            f"{min(mastered, 50)}/50题",
        ),
        _badge(
            "master_100",
            "掌握100题",
            "突破核心知识点",
            mastered >= 100,
            min(100, round(mastered / 100 * 100)),
            f"{min(mastered, 100)}/100题",
        ),
    ]


def _badge(
    key: str,
    title: str,
    desc: str,
    unlocked: bool,
    progress: int,
    progress_text: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "desc": desc,
        "unlocked": unlocked,
        "progress": progress,
        "progress_text": progress_text,
    }

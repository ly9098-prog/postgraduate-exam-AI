"""Pure ordered action recommendations from dashboard metrics."""


def _append_due(items, priority, overview):
    # 1. Overdue reviews
    if overview:
        due = overview.get("due_review_count", 0)
        if due > 0:
            priority += 1
            items.append(
                {
                    "type": "review",
                    "priority": priority,
                    "title": f"完成 {due} 道到期复习",
                    "desc": f"有 {due} 道复习题已到期，建议优先完成",
                    "action_data": {},
                }
            )

    return priority


def _append_repeat(items, priority, repeat_wrong):
    # 2. Repeat wrong rate high
    if repeat_wrong and repeat_wrong.get("is_high"):
        priority += 1
        count = repeat_wrong.get("repeat_wrong_count", 0)
        items.append(
            {
                "type": "wrong",
                "priority": priority,
                "title": f"复盘 {count} 道复发错题",
                "desc": f"错题复发率 {round(repeat_wrong['repeat_rate'] * 100)}%，建议集中复盘",
                "action_data": {},
            }
        )

    return priority


def _append_weak(items, priority, weak_topics):
    # 3. Weak topics exist
    if weak_topics and weak_topics.get("items"):
        top = weak_topics["items"][0]
        priority += 1
        items.append(
            {
                "type": "wrong",
                "priority": priority,
                "title": f"巩固「{top['name']}」知识点",
                "desc": f"该知识点掌握度 {top['mastery_score']} 分，错误 {top['wrong_count']} 次",
                "action_data": {"topic": top["name"]},
            }
        )

    return priority


def _append_balance(items, priority, new_vs_review):
    # 4. New vs review imbalance
    if new_vs_review:
        nr_label = new_vs_review.get("label", "")
        if "复习效果较好" in nr_label:
            priority += 1
            items.append(
                {
                    "type": "practice",
                    "priority": priority,
                    "title": "适当增加新题练习",
                    "desc": "复习效果较好，可以适当推进新题",
                    "action_data": {},
                }
            )
        elif "新题表现更佳" in nr_label:
            priority += 1
            items.append(
                {
                    "type": "review",
                    "priority": priority,
                    "title": "增加复习巩固",
                    "desc": "新题表现好但复习不足，建议平衡练习结构",
                    "action_data": {},
                }
            )

    return priority


def action_plan(overview, repeat_wrong, weak_topics, new_vs_review):
    items = []
    priority = _append_due(items, 0, overview)
    priority = _append_repeat(items, priority, repeat_wrong)
    priority = _append_weak(items, priority, weak_topics)
    _append_balance(items, priority, new_vs_review)
    # 5. Default: keep practicing
    if not items:
        items.append(
            {
                "type": "practice",
                "priority": 1,
                "title": "保持练习节奏",
                "desc": "当前状态良好，继续每日练习",
                "action_data": {},
            }
        )

    return {"data_available": True, "items": items}

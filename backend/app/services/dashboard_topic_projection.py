"""Pure weak-topic and repeated-error response projections."""


def weak_topic_items(items_data, due_counts, serialize):
    items = []
    for row in items_data:
        kp_id = row[0]
        items.append(
            {
                "knowledge_point_id": kp_id,
                "name": row[1],
                "subject_id": row[2],
                "subject_code": row[3] or "",
                "subject_name": row[4] or "",
                "mastery_score": round(row[5], 1),
                "attempt_count": row[6] or 0,
                "wrong_count": row[7] or 0,
                "recent_wrong_count": row[8] or 0,
                "due_review_count": due_counts.get(kp_id, 0),
                "last_practiced_at": (serialize(row[9]) if row[9] else None),
            }
        )
    return {"data_available": True, "items": items}


def fallback_weak_topics(rows):
    sorted_kps = [(str(name), int(count or 0)) for name, count in rows]
    if not sorted_kps:
        return None
    items = [
        {
            "knowledge_point_id": 0,
            "name": name,
            "subject_id": None,
            "subject_code": "",
            "subject_name": "",
            "mastery_score": max(0, 100 - count * 15),
            "attempt_count": count,
            "wrong_count": count,
            "recent_wrong_count": count,
            "due_review_count": 0,
            "last_practiced_at": None,
        }
        for name, count in sorted_kps
    ]
    return {"data_available": True, "items": items}


def repeat_wrong_analysis(total_wq, repeat_count, rate, top_topics):
    is_high = rate > 0.3
    if is_high:
        status_label = "偏高"
    elif rate > 0.15:
        status_label = "中等"
    else:
        status_label = "较低"

    return {
        "data_available": True,
        "repeat_wrong_count": repeat_count,
        "total_wrong_count": total_wq,
        "repeat_rate": round(rate, 4),
        "is_high": is_high,
        "status_label": status_label,
        "top_repeat_topics": top_topics,
    }

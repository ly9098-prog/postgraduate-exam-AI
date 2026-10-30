"""Pure speed/error classification and subject response rules."""


def classify_speed(avg_correct, avg_wrong, wrong_count, fast_wrong, slow_wrong):
    if avg_wrong > avg_correct * 1.3 and avg_wrong > 20:
        overall_status = "knowledge_gap"
        overall_label = "知识点不熟"
    elif fast_wrong > wrong_count * 0.3 and wrong_count > 5:
        overall_status = "hasty"
        overall_label = "审题不稳"
    elif slow_wrong > wrong_count * 0.3 and wrong_count > 5:
        overall_status = "unfamiliar"
        overall_label = "解法不熟"
    else:
        overall_status = "normal"
        overall_label = "速度正常"

    return overall_status, overall_label


def _speed_subjects(rows):
    by_subject = []
    for subj_id, subj_code, subj_name, ac, aw, cnt in rows:
        ac = float(ac or 0)
        aw = float(aw or 0)
        cnt = cnt or 0
        if cnt < 3:
            continue
        if aw > ac * 1.3 and aw > 15:
            sl = "知识点不熟"
        else:
            sl = "速度正常"
        by_subject.append(
            {
                "subject_id": subj_id,
                "subject_code": subj_code or "",
                "subject_name": subj_name or "",
                "avg_time_correct_sec": round(ac, 1),
                "avg_time_wrong_sec": round(aw, 1),
                "questions": cnt,
                "status_label": sl,
            }
        )

    return by_subject


def speed_accuracy(avg_correct, avg_wrong, fast_wrong, slow_wrong, status, rows):
    overall_status, overall_label = status
    by_subject = _speed_subjects(rows)
    return {
        "data_available": True,
        "overall_status": overall_status,
        "overall_label": overall_label,
        "avg_time_correct_sec": round(avg_correct, 1),
        "avg_time_wrong_sec": round(avg_wrong, 1),
        "fast_wrong_count": fast_wrong,
        "slow_wrong_count": slow_wrong,
        "by_subject": by_subject,
    }

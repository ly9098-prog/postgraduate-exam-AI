"""Pure daily quality and consistency rules for dashboard insights."""

import math
from datetime import timedelta


def today_quality(count, correct, avg_time):
    count = count or 0
    if count < 5:
        return None

    accuracy = correct / count if count > 0 else 0.0

    # Score components (0-100 each)
    acc_score = accuracy * 100  # 正确率分
    vol_score = min(100, (count / 20) * 100)  # 完成量分 (20题=满分)
    time_score = (
        100
        if avg_time and 20 <= avg_time <= 120
        else max(0, 100 - abs((avg_time or 60) - 60) * 0.5)
    )  # 用时稳定性

    total = acc_score * 0.4 + vol_score * 0.3 + time_score * 0.3

    if total >= 85:
        label = "优秀"
    elif total >= 70:
        label = "良好"
    elif total >= 50:
        label = "一般"
    else:
        label = "需要加油"

    return {
        "data_available": True,
        "score": round(total),
        "label": label,
        "questions": count,
        "accuracy": round(accuracy, 4),
        "avg_time_sec": round(avg_time, 1) if avg_time else 0.0,
    }


def _daily_values(rows):
    daily_data = {}
    for date_str, q_count, c_count in rows:
        daily_data[str(date_str)] = {
            "questions": q_count or 0,
            "correct": c_count or 0,
        }

    return daily_data


def _daily_breakdown(daily_data, today, days):
    q_values = []
    acc_values = []
    breakdown = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        dd = daily_data.get(d, {"questions": 0, "correct": 0})
        q_count = dd["questions"]
        acc = dd["correct"] / q_count if q_count > 0 else 0
        q_values.append(q_count)
        if q_count > 0:
            acc_values.append(acc)
        breakdown.append({"date": d, "questions": q_count, "accuracy": round(acc, 4)})

    return q_values, acc_values, breakdown


def _consistency_score(q_values, acc_values, days, active_ratio):
    mean_q = sum(q_values) / max(days, 1)
    var_q = sum((x - mean_q) ** 2 for x in q_values) / max(days, 1) if days > 0 else 0
    cv_q = math.sqrt(var_q) / max(mean_q, 1)

    # Accuracy std dev
    mean_acc = sum(acc_values) / max(len(acc_values), 1) if acc_values else 0
    acc_var = (
        sum((x - mean_acc) ** 2 for x in acc_values) / max(len(acc_values), 1)
        if acc_values
        else 0
    )
    acc_std = math.sqrt(acc_var)

    # Composite score (0-100)
    active_score = active_ratio * 100
    cv_score = max(0, 100 - min(cv_q * 60, 60))
    acc_stability = max(0, 100 - min(acc_std * 120, 60))
    total = active_score * 0.4 + cv_score * 0.35 + acc_stability * 0.25

    if total >= 80:
        label = "非常稳定"
    elif total >= 60:
        label = "较为稳定"
    else:
        label = "波动较大"

    return total, label


def weekly_consistency(rows, today, days):
    daily_data = _daily_values(rows)
    total_q = sum(d["questions"] for d in daily_data.values())
    if total_q < 5 or not daily_data:
        return None

    active_days = len(daily_data)
    active_ratio = active_days / max(days, 1)

    q_values, acc_values, breakdown = _daily_breakdown(daily_data, today, days)
    total, label = _consistency_score(q_values, acc_values, days, active_ratio)
    return {
        "data_available": True,
        "score": round(total),
        "label": label,
        "active_days": active_days,
        "days": days,
        "total_questions": total_q,
        "day_breakdown": breakdown,
    }

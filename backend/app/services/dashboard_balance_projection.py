"""Pure new/review balance and subject effort/return rules."""


def _practice_counts(rows):
    new_count = 0
    new_correct = 0
    review_count = 0
    review_correct = 0
    for ptype, cnt, corr in rows:
        if ptype == "new":
            new_count = cnt or 0
            new_correct = corr or 0
        else:
            review_count = cnt or 0
            review_correct = corr or 0

    return new_count, new_correct, review_count, review_correct


def _balance_label(new_count, review_count, new_acc, review_acc):
    if review_count >= 5 and new_count >= 5:
        if review_acc > new_acc + 0.1:
            label = "复习效果较好"
        elif new_acc > review_acc + 0.1:
            label = "新题表现更佳"
        else:
            label = "表现均衡"
    elif review_count < 5 and new_count >= 5:
        label = "侧重刷题"
    elif review_count >= 5 and new_count < 5:
        label = "侧重复习"
    else:
        label = "数据不足"

    return label


def _balance_summary(new_count, review_count, new_acc, review_acc):
    summary = ""
    if review_count >= 3 and new_count >= 3:
        diff = review_acc - new_acc
        if diff > 0.15:
            summary = f"复习题正确率高出{round(diff * 100)}%，复习效果明显"
        elif diff < -0.15:
            summary = "新题正确率更高，可以适当增加新题练习"
        else:
            summary = "新题和复习题表现接近，节奏均衡"
    elif new_count >= 5:
        summary = "新题练习较多，建议增加复习巩固"

    return summary


def new_vs_review(rows):
    new_count, new_correct, review_count, review_correct = _practice_counts(rows)
    total = new_count + review_count
    if total < 5:
        return None

    new_acc = new_correct / max(new_count, 1)
    review_acc = review_correct / max(review_count, 1)

    label = _balance_label(new_count, review_count, new_acc, review_acc)
    summary = _balance_summary(new_count, review_count, new_acc, review_acc)
    return {
        "data_available": True,
        "new_count": new_count,
        "new_accuracy": round(new_acc, 4),
        "review_count": review_count,
        "review_accuracy": round(review_acc, 4),
        "label": label,
        "summary": summary,
    }


def _subject_effort(rows):
    subject_data = {}
    total_q = 0
    total_time = 0
    for subj_id, subj_code, subj_name, cnt, corr, tm in rows:
        cnt = cnt or 0
        if cnt < 3:
            continue
        subject_data[subj_id] = {
            "subject_code": subj_code or "",
            "subject_name": subj_name or "",
            "questions": cnt,
            "correct": corr or 0,
            "time": tm or 0,
        }
        total_q += cnt
        total_time += tm or 0

    return subject_data, total_q, total_time


def _effort_item(subj_id, sd, global_avg):
    accuracy = sd["correct"] / max(sd["questions"], 1)
    time_per_q = sd["time"] / max(sd["questions"], 1)
    efficiency = accuracy / max(time_per_q / max(global_avg, 1), 0.1)

    if efficiency >= 1.2:
        eff_label = "高"
        suggestion = "继续保持当前学习方法"
    elif efficiency >= 0.8:
        eff_label = "中"
        suggestion = "提升空间较大，建议侧重薄弱知识点"
    else:
        eff_label = "低"
        suggestion = "投入时间多但收益偏低，建议先复盘错题"

    # Accuracy overrides — only when they don't mask efficiency concerns
    if accuracy < 0.6 and sd["questions"] >= 10:
        suggestion = "正确率偏低，建议减少盲目刷题，优先复盘错题"
    elif accuracy >= 0.85 and efficiency >= 1.0:
        suggestion = "掌握良好，可以保持节奏"
    elif accuracy >= 0.85 and efficiency < 0.8:
        suggestion = "耗时较长但正确率尚可，建议优化做题速度"

    return {
        "subject_id": subj_id,
        "subject_code": sd["subject_code"],
        "subject_name": sd["subject_name"],
        "total_questions": sd["questions"],
        "total_duration_sec": sd["time"],
        "accuracy": round(accuracy, 4),
        "time_per_question_sec": round(time_per_q, 1),
        "efficiency_score": round(efficiency, 2),
        "efficiency_label": eff_label,
        "suggestion": suggestion,
    }


def input_output(rows):
    subject_data, total_q, total_time = _subject_effort(rows)
    if not subject_data or total_q < 5:
        return None

    global_avg = total_time / max(total_q, 1)

    items = [
        _effort_item(subj_id, sd, global_avg) for subj_id, sd in subject_data.items()
    ]
    items.sort(key=lambda x: x["efficiency_score"])
    return {
        "data_available": True,
        "items": items,
        "global_avg_time_sec": round(global_avg, 1),
    }

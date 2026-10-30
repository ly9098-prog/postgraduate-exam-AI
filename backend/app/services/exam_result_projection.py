"""Exam result response projections; grading and transaction ownership stays with the service."""


def question_result(
    answer,
    item,
    revision,
    subject,
    item_score,
    earned,
    selected,
    is_correct,
    status,
    names,
    wrong_question_id,
    error_diagnosis_payload,
    ports,
):
    return {
        "item_id": int(item.id),
        "question_id": int(answer.question_id),
        "question_version_id": int(answer.question_version_id),
        "position": int(item.position),
        "subject_id": int(subject.id),
        "subject_code": subject.code,
        "subject_name": subject.name,
        "score": ports._money(item_score),
        "earned_score": ports._money(earned),
        "selected_answer": selected,
        "correct_answer": str(revision.answer or ""),
        "is_correct": is_correct,
        "status": status,
        "marked_for_review": bool(answer.marked_for_review),
        "used_time": int(answer.used_time or 0),
        "content": ports._student_content(revision.content),
        "options": ports._student_options(revision.options),
        "analysis": revision.analysis,
        "image_url": revision.image_url,
        "knowledge_points": list(names),
        "wrong_question_id": wrong_question_id,
        "error_diagnosis": error_diagnosis_payload,
    }


def subject_breakdown(subject_stats, ports):
    subject_breakdown = []
    for stats in subject_stats.values():
        answered = int(stats["answered_count"])
        correct = int(stats["correct_count"])
        subject_breakdown.append(
            {
                "subject_id": stats["subject_id"],
                "subject_code": stats["subject_code"],
                "subject_name": stats["subject_name"],
                "question_count": int(stats["question_count"]),
                "answered_count": answered,
                "correct_count": correct,
                "score": ports._money(stats["score"]),
                "total_score": ports._money(stats["total_score"]),
                "accuracy": round(correct / int(stats["question_count"]), 4)
                if int(stats["question_count"])
                else 0.0,
            }
        )
    subject_order = {code: idx for idx, code in enumerate(ports.EXAM408_CORE_CODES)}
    subject_breakdown.sort(key=lambda x: subject_order.get(x["subject_code"], 99))
    return subject_breakdown


def weak_knowledge_points(kp_losses, kp_lost_score):
    return [
        {
            "name": name,
            "miss_count": int(count),
            "lost_score": round(kp_lost_score[name], 2),
        }
        for name, count in kp_losses.most_common(8)
    ]


def result_snapshot(
    attempt,
    paper,
    terminal_status,
    now,
    duration,
    totals,
    subject_breakdown,
    weak_kps,
    result_questions,
    ports,
):
    return {
        "attempt_id": int(attempt.id),
        "paper_id": int(paper.id),
        "paper_title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "attempt_status": terminal_status,
        "started_at": ports.normalize_to_naive_utc(attempt.started_at).isoformat(),
        "submitted_at": ports.normalize_to_naive_utc(now).isoformat(),
        "duration_sec": int(duration),
        "question_count": int(totals["question_count"]),
        "answered_count": int(totals["answered_count"]),
        "correct_count": int(totals["total_correct"]),
        "wrong_count": int(totals["wrong_count"]),
        "unanswered_count": int(totals["unanswered_count"]),
        "choice_score": ports._money(totals["earned_total"]),
        "total_choice_score": ports._money(totals["total_score"]),
        "accuracy": round(totals["total_correct"] / totals["question_count"], 4)
        if totals["question_count"]
        else 0.0,
        "subject_breakdown": subject_breakdown,
        "weak_knowledge_points": weak_kps,
        "questions": result_questions,
    }

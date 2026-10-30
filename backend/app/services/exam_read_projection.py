"""Read-only exam response projections; query and lifecycle ownership stays with the service."""


def paper_list(papers, attempts_by_paper, ports):
    result: list[dict] = []
    for paper, question_count, total_score in papers:
        attempts = attempts_by_paper.get(int(paper.id), [])
        latest = next((a for a in attempts if a.status != "abandoned"), None)
        latest_status = latest.status if latest else None
        if (
            latest is not None
            and latest_status == "in_progress"
            and paper.duration_sec
            and (ports._elapsed_seconds(latest.started_at) >= int(paper.duration_sec))
        ):
            latest_status = "expired"
        terminal_scores = [
            ports._money(a.score)
            for a in attempts
            if a.status in ports.TERMINAL_ATTEMPT_STATUSES
        ]
        result.append(
            {
                "id": int(paper.id),
                "title": paper.title,
                "paper_type": paper.paper_type,
                "year": paper.year,
                "source": paper.source,
                "duration_sec": paper.duration_sec,
                "version": int(paper.version),
                "question_count": int(question_count),
                "total_choice_score": ports._money(total_score),
                "latest_attempt_id": int(latest.id) if latest else None,
                "latest_attempt_status": latest_status,
                "best_choice_score": max(terminal_scores) if terminal_scores else None,
            }
        )
    return result


def paper_detail(
    paper,
    question_count,
    total_score,
    latest,
    latest_status,
    terminal_scores,
    dist_rows,
    ports,
):
    return {
        "id": int(paper.id),
        "title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "source": paper.source,
        "duration_sec": paper.duration_sec,
        "version": int(paper.version),
        "question_count": question_count,
        "total_choice_score": total_score,
        "latest_attempt_id": int(latest.id) if latest else None,
        "latest_attempt_status": latest_status,
        "best_choice_score": max(terminal_scores) if terminal_scores else None,
        "subject_distribution": [
            {
                "subject_id": int(sid),
                "subject_code": code,
                "subject_name": name,
                "question_count": int(count),
                "total_score": ports._money(score),
            }
            for sid, code, name, count, score in dist_rows.all()
        ],
    }


def attempt_question(answer, item, revision, subject, ports):
    return {
        "item_id": int(item.id),
        "question_id": int(answer.question_id),
        "question_version_id": int(answer.question_version_id),
        "position": int(item.position),
        "score": ports._money(item.score),
        "subject_id": int(item.section_subject_id),
        "subject_code": subject.code,
        "subject_name": subject.name,
        "question_type": ports.QT_SINGLE_CHOICE,
        "content": ports._student_content(revision.content),
        "options": ports._student_options(revision.options),
        "image_url": revision.image_url,
    }


def attempt_answer(answer, item):
    return {
        "item_id": int(item.id),
        "selected_answer": answer.selected_answer,
        "marked_for_review": bool(answer.marked_for_review),
        "used_time": int(answer.used_time or 0),
        "answered_at": answer.answered_at,
    }


def attempt_view(
    attempt, paper, elapsed, remaining, question_count, total_score, questions, answers
):
    return {
        "id": int(attempt.id),
        "paper_id": int(paper.id),
        "paper_title": paper.title,
        "paper_type": paper.paper_type,
        "year": paper.year,
        "status": attempt.status,
        "started_at": attempt.started_at,
        "duration_limit_sec": paper.duration_sec,
        "elapsed_sec": elapsed,
        "remaining_sec": remaining,
        "question_count": question_count,
        "total_choice_score": total_score,
        "questions": questions,
        "answers": answers,
    }


def saved_answer(attempt, answer, item_id):
    return {
        "attempt_id": int(attempt.id),
        "status": attempt.status,
        "answer": {
            "item_id": int(item_id),
            "selected_answer": answer.selected_answer,
            "marked_for_review": bool(answer.marked_for_review),
            "used_time": int(answer.used_time or 0),
            "answered_at": answer.answered_at,
        },
    }


def history_item(row, ports):
    question_count = max(0, int(row.question_count or 0))
    answered_count = max(0, min(question_count, int(row.answered_count or 0)))
    correct_count = max(0, min(answered_count, int(row.correct_count or 0)))
    wrong_count = max(0, answered_count - correct_count)
    unanswered_count = max(0, question_count - answered_count)
    accuracy = round(correct_count / question_count, 4) if question_count else 0.0
    return {
        "attempt_id": int(row.attempt_id),
        "paper_id": int(row.paper_id),
        "paper_title": row.paper_title or f"试卷 #{row.paper_id}",
        "paper_type": row.paper_type or "mock_choice",
        "year": row.year,
        "status": row.status,
        "started_at": row.started_at,
        "submitted_at": row.submitted_at,
        "duration_sec": int(row.duration_sec or 0),
        "question_count": question_count,
        "answered_count": answered_count,
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "unanswered_count": unanswered_count,
        "choice_score": ports._money(row.choice_score),
        "total_choice_score": ports._money(row.total_choice_score),
        "accuracy": accuracy,
    }


def history_summary(summary_row, completed_count):
    return {
        "completed_count": completed_count,
        "average_choice_score": round(float(summary_row.average_choice_score or 0), 2),
        "average_total_choice_score": round(
            float(summary_row.average_total_choice_score or 0), 2
        ),
        "average_accuracy": round(float(summary_row.average_accuracy or 0), 4),
        "best_choice_score": round(float(summary_row.best_choice_score or 0), 2),
        "best_accuracy": round(float(summary_row.best_accuracy or 0), 4),
    }

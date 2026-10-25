"""Sequential reservation release predicate for committed practice batches."""

from __future__ import annotations

from sqlalchemy import delete

from app.models.sequential_reservation import SequentialReservation


def build_sequential_reservation_cleanup(
    *,
    user_id: int,
    batch_payload: dict,
    all_question_ids: list[int],
):
    request_id = batch_payload.get("seq_reservation_request_id")
    if not request_id or str(batch_payload.get("mode")) != "sequential":
        return None
    return delete(SequentialReservation).where(
        SequentialReservation.user_id == user_id,
        SequentialReservation.subject_id == int(batch_payload.get("sid") or 0),
        SequentialReservation.start_request_id == str(request_id),
        SequentialReservation.question_id.in_(all_question_ids),
    )

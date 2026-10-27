"""Shared doubles for claimed practice-batch transaction contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Persisted:
    records: list
    prewarm_wrong_questions: list
    wrong_question_ids: dict


class SessionObj:
    def __init__(self, events):
        self.events = events
        self._submission_response = None

    @property
    def submission_response(self):
        return self._submission_response

    @submission_response.setter
    def submission_response(self, value):
        self.events.append(("response-set", value))
        self._submission_response = value


def overrides(events):
    return {
        "session_obj": SessionObj(events),
        "persist_records": None,
        "load_revision_kp_names": None,
        "build_response_by_question": None,
        "build_response": lambda **kwargs: {"response": True},
        "persisted_knowledge_session": object(),
        "build_cleanup": lambda **kwargs: "cleanup",
        "execute": None,
        "commit": None,
        "rollback": None,
        "persist_records_kwargs": {"user_id": 8},
        "issued_revisions": {1: 11, 2: 22},
        "issued_order": [1, 2],
        "skipped_questions": [],
        "total_correct": 1,
        "total_wrong": 1,
        "knowledge_context": {"root": 1},
        "entry_context": {"source": "test"},
        "user_id": 8,
        "batch_payload": {"rid": "submit-1"},
        "all_question_ids": [1, 2],
    }

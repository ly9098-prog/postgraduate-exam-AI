"""Deterministic ports for knowledge-session summary characterization."""

from types import SimpleNamespace

from app.services import knowledge_map_service
from app.services.practice import knowledge_session_summary as svc


class Rows:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class Database:
    def __init__(self, *, session=None, execute=(), scalars=(), failure=None):
        self.session = session
        self.queues = {"execute": list(execute), "scalars": list(scalars)}
        self.events = []
        self.sql = []
        self.failure = failure

    def record(self, channel, statement):
        self.events.append(channel)
        compiled = statement.compile()
        self.sql.append((channel, str(compiled), compiled.params))
        if self.failure and self.failure[0] == channel:
            raise self.failure[1]

    async def scalar(self, statement):
        self.record("scalar", statement)
        return self.session

    async def execute(self, statement):
        self.record("execute", statement)
        return Rows(self.queues["execute"].pop(0))

    async def scalars(self, statement):
        self.record("scalars", statement)
        return Rows(self.queues["scalars"].pop(0))


def root_port(monkeypatch, db, detail=None, error=None):
    async def load(actual_db, user_id, root_id):
        assert actual_db is db
        assert user_id == 7
        db.events.append(("root", root_id))
        if error:
            raise error
        return detail

    monkeypatch.setattr(knowledge_map_service, "get_point_detail", load)


def state(kp_id, mastery=70, confidence=0.8, attempts=3):
    return SimpleNamespace(
        knowledge_point_id=kp_id,
        mastery_score=mastery,
        confidence=confidence,
        attempt_count=attempts,
    )


def legacy(points=None, root=None):
    return {
        "practice_mode": "knowledge_chapter",
        "root_knowledge_point_id": 12,
        "root_name": "signed name",
        "include_descendants": True,
        "knowledge_point_count": 4,
        "_baseline": {"points": points or [], "root": root},
    }


def session(knowledge=None, *, results=None, snapshot=None):
    response = {"results": results or []}
    if knowledge is not None:
        response["knowledge_session"] = knowledge
    return SimpleNamespace(submission_response=response, scope_snapshot=snapshot)


def record(rid, revision=101, *, correct=False, projection="applied"):
    return SimpleNamespace(
        id=rid,
        question_version_id=revision,
        is_correct=correct,
        projection_state=projection,
    )


async def read(db, request_id=" req "):
    return await svc.get_session_knowledge_summary(db, user_id=7, request_id=request_id)

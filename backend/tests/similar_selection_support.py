"""Synthetic ports for the similar-mode service entry."""

import sys
from types import SimpleNamespace

from sqlalchemy import select

from app.models.question import Question
from app.services import practice_service as svc


class SimilarHarness:
    def __init__(self, monkeypatch):
        import app.services as services

        self.db = object()
        self.scope = [8, 9]
        self.questions = [SimpleNamespace(id=qid) for qid in (4, 2, 4)]
        self.fill = [SimpleNamespace(id=qid) for qid in (7, 8)]
        self.metadata = {4: {"strategy": "vector"}, 99: {"unreturned": True}}
        self.events = []
        self.requests = []
        self.fill_calls = []
        self.exclusions = []
        self.errors = {}
        self.revision_calls = []
        self.exclude_options = []
        self.random_sample = object()
        self.logger = object()
        self.vector = SimpleNamespace(search_similar_questions=object())
        monkeypatch.setitem(
            sys.modules, "app.services.vector_retrieval_service", self.vector
        )
        monkeypatch.setattr(
            services, "vector_retrieval_service", self.vector, raising=False
        )
        for name, port in {
            "resolve_subject_ids": self.resolve,
            "_build_excluded_question_subquery": self.excluded,
            "_practice_revision_scope_condition": self.revision,
            "load_similar_vector_questions": self.recall,
            "load_similar_fill_questions": self.supplement,
            "apply_fill_metadata": self.project,
            "_random_sample_query": self.random_sample,
            "logger": self.logger,
        }.items():
            monkeypatch.setattr(svc, name, port)

    def event(self, name):
        self.events.append(name)
        if name in self.errors:
            raise self.errors[name]

    async def resolve(self, db, code):
        assert db is self.db and code == "cs"
        self.event("resolve")
        return self.scope

    def excluded(self, **kwargs):
        self.event("exclude")
        self.exclude_options.append(kwargs)
        result = select(Question.id).where(Question.id == 100 + len(self.exclusions))
        self.exclusions.append(result)
        return result

    def revision(self, ids):
        self.event("revision")
        condition = Question.difficulty >= 2
        self.revision_calls.append((ids, condition))
        return condition

    async def recall(self, request):
        self.requests.append(request)
        self.event("recall")
        return self.questions, self.metadata

    async def supplement(self, *args):
        self.fill_calls.append(args)
        self.event("fill")
        return self.fill

    def project(self, metadata, questions):
        self.event("metadata")
        from app.services.practice.similar_supplement import apply_fill_metadata

        return apply_fill_metadata(metadata, questions)

    async def run(self, **kwargs):
        return await svc.get_similar_practice_questions(self.db, 7, "cs", 42, **kwargs)

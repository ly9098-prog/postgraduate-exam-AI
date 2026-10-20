"""Resolve the real outbox adapter through each runtime consumer."""

from app import main
from app.services import runtime_scheduler_startup


def outbox_enqueue_factory(entry):
    return (main if entry == "http" else runtime_scheduler_startup).build_outbox_enqueue

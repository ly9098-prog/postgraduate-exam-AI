"""Resolve the real outbox adapter through each runtime consumer."""

from app.services import runtime_http_scheduler_startup, runtime_scheduler_startup


def outbox_enqueue_factory(entry):
    if entry == "http":
        return runtime_http_scheduler_startup.build_outbox_enqueue
    return runtime_scheduler_startup.build_outbox_enqueue

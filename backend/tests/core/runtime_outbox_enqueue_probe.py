"""Resolve the real outbox adapter through each runtime consumer."""

from app import main
from app.core import bootstrap


def outbox_enqueue_factory(entry):
    return (main if entry == "http" else bootstrap).build_outbox_enqueue

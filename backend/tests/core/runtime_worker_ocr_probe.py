"""Resolve the worker assembly implementation through its real owner."""

from app.services.runtime_ocr_startup import initialize_worker_ocr_gateway


def worker_ocr_operation():
    return initialize_worker_ocr_gateway

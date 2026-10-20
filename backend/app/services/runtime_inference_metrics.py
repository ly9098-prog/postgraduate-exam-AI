"""Prometheus samples from OCR and AI runtime guards without owning their state."""


def append_ocr_metrics(lines: list[str]) -> None:
    _append = lines.append
    try:
        from app.services.ocr_service import get_gateway

        gateway = get_gateway()
        if gateway is not None:
            wm = gateway.worker_metrics
            _append(f'ocr_circuit_state{{backend="{wm.get("backend", "?")}"}} 1')
            state = wm.get("circuit_state", "unknown")
            _append(
                f'ocr_circuit{{backend="{wm.get("backend", "?")}",state="{state}"}} 1'
            )
            _append(
                f"ocr_circuit_breaker_rejected_total "
                f"{wm.get('circuit_breaker_rejected', 0)}"
            )
            _append(
                f"ocr_circuit_breaker_trips_total {wm.get('circuit_breaker_trips', 0)}"
            )
            _append(f"ocr_accepted_total {wm.get('accepted', 0)}")
            _append(f"ocr_failed_total {wm.get('failed', 0)}")
            _append(f"ocr_timed_out_total {wm.get('timed_out', 0)}")
            _append(f"ocr_connection_errors_total {wm.get('connection_errors', 0)}")
    except Exception:
        _append("ocr_circuit 0")


async def append_ai_metrics(lines: list[str]) -> None:
    _append = lines.append
    try:
        from app.core.ai_runtime_guard import ai_runtime_guard

        am = ai_runtime_guard.metrics_snapshot()
        _append(f"ai_requests_total {am.get('requests', 0)}")
        _append(f"ai_success_total {am.get('success', 0)}")
        _append(f"ai_failures_total {am.get('failures', 0)}")
        _append(f"ai_tokens_total {am.get('tokens', 0)}")
        _append(f"ai_in_flight {am.get('in_flight', 0)}")
        _append(f"ai_queue_wait_ms_total {am.get('queue_wait_ms_total', 0)}")
        _append(f"ai_queue_wait_ms_avg {am.get('queue_wait_ms_avg', 0)}")
        _append(
            f'ai_rejected_total{{reason="rate_limit"}} {am.get("rejected_rate_limit", 0)}'
        )
        _append(
            f'ai_rejected_total{{reason="overload"}} {am.get("rejected_overload", 0)}'
        )
        _append(
            f'ai_rejected_total{{reason="circuit"}} {am.get("rejected_circuit", 0)}'
        )
        _append(
            f'ai_rejected_total{{reason="prompt_too_large"}} {am.get("rejected_prompt_too_large", 0)}'
        )
        _append(f"ai_circuit_trips_total {am.get('circuit_trips', 0)}")
        _append(f"ai_open_circuits {am.get('open_circuits', 0)}")
        from app.features.token_budget import get_shared_token_usage_snapshot

        budget = await get_shared_token_usage_snapshot()
        _append(f"ai_pipeline_tokens_daily {budget.get('daily', 0)}")
        _append(f"ai_pipeline_tokens_monthly {budget.get('monthly', 0)}")
        _append(f"ai_pipeline_token_budget_shared {1 if budget.get('shared') else 0}")
    except Exception:
        _append("ai_runtime_metrics_available 0")

"""Prometheus output for SSE health, connection counts and import counters."""


async def append_sse_metrics(lines: list[str]) -> None:
    _append = lines.append
    try:
        from app.services.sse_pubsub import check_health as _sse_health

        _sse_ok = await _sse_health()
        _append(f"sse_healthy {1 if _sse_ok else 0}")
    except Exception:
        _append("sse_healthy 0")
    try:
        import app.features.batch_image_import_service as _batch_svc_mod

        _active_sse = getattr(_batch_svc_mod, "_active_sse_connections", {})
        _total_sse = sum(_active_sse.values()) if isinstance(_active_sse, dict) else 0
        _append(f"sse_active_connections {_total_sse}")
    except Exception:
        _append("sse_active_connections 0")
    try:
        from app.services.import_sse_metrics import counters as _sse_m

        if isinstance(_sse_m, dict):
            for _sk, _sv in _sse_m.items():
                _append(f"sse_{_sk} {_sv}")
    except Exception:
        pass

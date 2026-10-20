"""Single process-local owner of the existing import SSE counters."""

# ── SSE low-cardinality metrics ──
# Counters; no user_id label (high cardinality).
# Per-user connection counts stored in batch_image_import_service._active_sse_connections.
counters: dict[str, int] = {
    "active": 0,
    "per_user_rejected": 0,
    "global_rejected": 0,
    "disconnected": 0,
    "max_duration_closed": 0,
    "max_idle_closed": 0,
}

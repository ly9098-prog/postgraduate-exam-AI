"""Export WebSocket correlation, authentication and handoff."""

from __future__ import annotations


async def export_status_ws(ws, *, ports):
    """WebSocket endpoint for real-time export task status.

    Authentication: pass ``["bearer", "<JWT>"]`` as WebSocket subprotocols.
    Query-string tokens are accepted only in local development or when the
    explicitly unsafe compatibility flag is enabled.
    The user will receive export task status events for their own tasks.

    Protocol:
    - Client sends ``{"type": "ping"}`` → server responds ``{"type": "pong"}``
    - Server sends ``{"type": "export_status", "task_id": ..., ...}``
    - Server sends ``{"type": "ping"}`` periodically (heartbeat)
    """
    from app.core.config import settings
    from app.core.log_context import (
        bind_log_context,
        normalize_request_id,
        normalize_trace_id,
        reset_log_context,
    )

    log_tokens = bind_log_context(
        trace_id=normalize_trace_id(
            ws.headers.get("x-trace-id"), ws.headers.get("traceparent")
        ),
        request_id=normalize_request_id(ws.headers.get("x-request-id")),
    )
    try:
        await serve_authenticated_socket(
            ws, settings, log_tokens, bind_log_context, ports=ports
        )
    finally:
        reset_log_context(log_tokens)


async def serve_authenticated_socket(
    ws, settings, log_tokens, bind_log_context, *, ports
):
    if not settings.EXPORT_WEBSOCKET_ENABLED:
        await ws.close(code=4001, reason="实时推送功能已关闭")
        return
    offered_protocols = [
        item.strip()
        for item in ws.headers.get("sec-websocket-protocol", "").split(",")
        if item.strip()
    ]
    token = ""
    selected_subprotocol = None
    if "bearer" in offered_protocols:
        index = offered_protocols.index("bearer")
        if index + 1 < ports("len")(offered_protocols):
            token = offered_protocols[index + 1]
            selected_subprotocol = "bearer"
    local_env = settings.APP_ENV.lower() in {"development", "local", "test"}
    if not token and (local_env or settings.ALLOW_LEGACY_WEBSOCKET_QUERY_TOKEN):
        token = ws.query_params.get("token", "")
    if not token:
        await ws.close(code=4001, reason="Missing token")
        return
    try:
        from app.core.database import async_session
        from app.core.security import authenticate_user_token

        async with async_session() as db:
            user, _payload = await authenticate_user_token(token, db)
        user_id = user.id
        log_tokens.extend(bind_log_context(user_id=user_id))
    except ports("Exception"):
        await ws.close(code=4001, reason="Invalid token")
        return
    ports("logger").info("export_websocket_connected", extra={"user_id": user_id})
    from app.services.export.push_service import handle_export_ws

    await handle_export_ws(
        ws, user_id, auth_token=token, subprotocol=selected_subprotocol
    )

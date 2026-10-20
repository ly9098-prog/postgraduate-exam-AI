"""Public HTTP error codes, status mapping and safe correlation envelope."""

from fastapi import Request

from app.core.error_codes import ErrorCode

_PUBLIC_HTTP_MESSAGES: dict[int, str] = {
    400: "请求参数有误，请检查后重试",
    401: "登录状态已失效，请重新登录",
    403: "没有权限执行此操作",
    404: "请求的资源不存在",
    405: "请求方式不支持",
    409: "当前数据状态已变化，请刷新后重试",
    413: "上传内容过大，请调整后重试",
    415: "不支持的内容类型",
    422: "提交内容校验未通过，请检查后重试",
    429: "请求过于频繁，请稍后重试",
    500: "服务器内部错误，请稍后重试",
    502: "服务暂时不可用，请稍后重试",
    503: "服务暂时不可用，请稍后重试",
    504: "服务响应超时，请稍后重试",
}


def _public_http_message(status_code: int) -> str:
    if status_code in _PUBLIC_HTTP_MESSAGES:
        return _PUBLIC_HTTP_MESSAGES[status_code]
    if status_code >= 500:
        return "服务暂时不可用，请稍后重试"
    if status_code >= 400:
        return "请求失败，请检查后重试"
    return "请求失败，请稍后重试"


def _extract_public_error_code(detail: object, status_code: int) -> str:
    """Keep a stable machine-readable code without exposing backend text."""
    import re

    value: object | None = None
    if isinstance(detail, dict):
        value = detail.get("error_code") or detail.get("code")
        if value is None and isinstance(detail.get("detail"), dict):
            nested = detail["detail"]
            value = nested.get("error_code") or nested.get("code")
    elif isinstance(detail, str):
        value = detail

    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value):
        return value
    return f"HTTP_{status_code}"


def _request_error_ids(request: Request) -> tuple[str, str]:
    try:
        from app.core.log_context import get_log_context

        context = get_log_context()
    except Exception:
        context = {}
    request_id = str(
        context.get("request_id") or request.headers.get("x-request-id") or ""
    )
    trace_id = str(context.get("trace_id") or request.headers.get("x-trace-id") or "")
    return request_id, trace_id


def _public_error_content(
    request: Request,
    *,
    status_code: int,
    code: str,
    retryable: bool = False,
) -> dict:
    request_id, trace_id = _request_error_ids(request)
    error: dict[str, object] = {
        "code": code,
        "message": _public_http_message(status_code),
        "retryable": retryable,
    }
    if request_id:
        error["request_id"] = request_id
    if trace_id:
        error["trace_id"] = trace_id
    return {"error": error}


def _api_error_status(code: ErrorCode) -> int:
    codes_503 = {
        ErrorCode.QUEUE_UNAVAILABLE,
        ErrorCode.DB_UNAVAILABLE,
        ErrorCode.STAGING_UNAVAILABLE,
        ErrorCode.OCR_PROVIDER_ERROR,
        ErrorCode.AI_PROVIDER_UNAVAILABLE,
        ErrorCode.RESOURCE_MEMORY_LOW,
        ErrorCode.RESOURCE_DISK_LOW,
    }
    codes_429 = {
        ErrorCode.QUEUE_FULL,
        ErrorCode.RESOURCE_QUEUE_FULL,
        ErrorCode.OCR_RATE_LIMIT,
        ErrorCode.AI_RATE_LIMIT,
        ErrorCode.AI_OVERLOADED,
        ErrorCode.RESOURCE_DB_POOL_BUSY,
    }
    codes_409 = {
        ErrorCode.DB_CONFLICT,
        ErrorCode.TASK_FENCING_REJECTED,
        ErrorCode.TASK_LEASE_LOST,
        ErrorCode.TASK_CANCELLED,
    }
    codes_404 = {
        ErrorCode.TASK_NOT_FOUND,
        ErrorCode.STAGING_OBJECT_MISSING,
    }
    codes_422 = {
        ErrorCode.REVIEW_REQUIRED,
        ErrorCode.VALIDATION_ERROR,
    }
    codes_504 = {
        ErrorCode.OCR_TIMEOUT,
        ErrorCode.AI_TIMEOUT,
        ErrorCode.PIPELINE_TIMEOUT,
    }
    if code in codes_503:
        return 503
    if code in codes_429:
        return 429
    if code in codes_409:
        return 409
    if code in codes_404:
        return 404
    if code in codes_422:
        return 422
    if code in codes_504:
        return 504
    return 500

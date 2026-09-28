"""Pure health-rule evaluation for async task diagnostics.

This module deliberately has no database/Redis/model imports so health policy can
be unit-tested in the lightweight local environment.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings


def evaluate_task_health(
    *,
    outbox: dict[str, Any],
    redis: dict[str, Any],
    projection: dict[str, Any],
    async_runtime_expected: bool,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    def issue(
        code: str, severity: str, message: str, value: int | float | None = None
    ) -> None:
        issues.append(
            {"code": code, "severity": severity, "message": message, "value": value}
        )

    if async_runtime_expected:
        if not redis.get("configured"):
            issue(
                "REDIS_NOT_CONFIGURED",
                "error",
                "异步任务运行需要 Redis，但当前未配置。",
            )
        elif not redis.get("available"):
            issue(
                "REDIS_UNAVAILABLE",
                "error",
                "Redis 当前不可用，异步任务已无法正常投递或消费。",
            )
        else:
            memory = redis.get("memory")
            if memory is None:
                issue(
                    "REDIS_MEMORY_METRICS_UNAVAILABLE",
                    "warning",
                    "Redis 队列可用，但内存指标暂不可观测。",
                )
            elif int(memory.get("max_bytes") or 0) <= 0:
                issue(
                    "REDIS_MEMORY_LIMIT_UNSET",
                    "warning",
                    "Redis 未设置内存上限，无法预警容量耗尽。",
                )
            else:
                usage_pct = round(
                    100 * int(memory.get("used_bytes") or 0) / int(memory["max_bytes"]),
                    2,
                )
                if usage_pct >= settings.TASK_HEALTH_REDIS_MEMORY_ERROR_PCT:
                    issue(
                        "REDIS_MEMORY_CRITICAL",
                        "error",
                        "Redis 内存占用达到严重阈值，noeviction 模式下写入可能失败。",
                        usage_pct,
                    )
                elif usage_pct >= settings.TASK_HEALTH_REDIS_MEMORY_WARN_PCT:
                    issue(
                        "REDIS_MEMORY_HIGH",
                        "warning",
                        "Redis 内存占用达到预警阈值。",
                        usage_pct,
                    )
            if memory is not None and int(memory.get("evicted_keys") or 0) > 0:
                issue(
                    "REDIS_KEYS_EVICTED",
                    "warning",
                    "Redis 已出现键淘汰，请检查内存策略和历史事件。",
                    int(memory["evicted_keys"]),
                )

            key_sample = redis.get("projection_keys")
            if key_sample is not None:
                if not key_sample.get("available"):
                    issue(
                        "REDIS_PROJECTION_SCAN_UNAVAILABLE",
                        "warning",
                        "答题投影键巡检失败，键数量和 TTL 状态暂不可观测。",
                    )
                else:
                    no_ttl = int(key_sample.get("idempotent_no_ttl") or 0)
                    if no_ttl:
                        issue(
                            "REDIS_PROJECTION_GUARD_NO_TTL",
                            "error",
                            "答题投影幂等键缺少 TTL，可能持续占用 Redis 内存。",
                            no_ttl,
                        )
                    if not key_sample.get("complete"):
                        issue(
                            "REDIS_PROJECTION_SCAN_INCOMPLETE",
                            "warning",
                            "答题投影键巡检达到扫描预算，部分计数不是全量结果。",
                        )

        oldest_outbox = int(outbox.get("oldest_unpublished_seconds") or 0)
        if oldest_outbox >= settings.TASK_HEALTH_OUTBOX_OLDEST_ERROR_SEC:
            issue(
                "OUTBOX_STALLED",
                "error",
                "Outbox 存在长时间未发布任务。",
                oldest_outbox,
            )
        elif oldest_outbox >= settings.TASK_HEALTH_OUTBOX_OLDEST_WARN_SEC:
            issue(
                "OUTBOX_DELAYED",
                "warning",
                "Outbox 发布延迟超过预警阈值。",
                oldest_outbox,
            )

        oldest_ready = int(redis.get("oldest_ready_seconds") or 0)
        if oldest_ready >= settings.TASK_HEALTH_QUEUE_OLDEST_ERROR_SEC:
            issue(
                "QUEUE_STALLED",
                "error",
                "Redis 队列存在长时间未消费任务。",
                oldest_ready,
            )
        elif oldest_ready >= settings.TASK_HEALTH_QUEUE_OLDEST_WARN_SEC:
            issue(
                "QUEUE_DELAYED",
                "warning",
                "Redis 队列等待时间超过预警阈值。",
                oldest_ready,
            )

        dead = int((redis.get("totals") or {}).get("dead", 0))
        corrupt = int((redis.get("totals") or {}).get("corrupt", 0))
        terminal_bad = dead + corrupt
        if terminal_bad >= settings.TASK_HEALTH_DEAD_ERROR_COUNT:
            issue(
                "TASK_DEADLETTER_HIGH",
                "error",
                "死信/损坏任务数量达到错误阈值。",
                terminal_bad,
            )
        elif terminal_bad >= settings.TASK_HEALTH_DEAD_WARN_COUNT:
            issue(
                "TASK_DEADLETTER_PRESENT",
                "warning",
                "存在需要人工关注的死信或损坏任务。",
                terminal_bad,
            )

        unprojected = int(projection.get("unprojected") or 0)
        if unprojected >= settings.TASK_HEALTH_PROJECTION_ERROR_COUNT:
            issue(
                "ANSWER_PROJECTION_BACKLOG_HIGH",
                "error",
                "答题派生状态存在较大积压。",
                unprojected,
            )
        elif unprojected >= settings.TASK_HEALTH_PROJECTION_WARN_COUNT:
            issue(
                "ANSWER_PROJECTION_BACKLOG",
                "warning",
                "存在超过宽限时间仍未完成的答题投影。",
                unprojected,
            )

    failed_outbox = int((outbox.get("counts") or {}).get("failed", 0))
    if failed_outbox >= settings.TASK_HEALTH_FAILED_OUTBOX_ERROR_COUNT:
        issue(
            "OUTBOX_FAILED_HIGH",
            "error",
            "Outbox 永久失败任务数量达到错误阈值。",
            failed_outbox,
        )
    elif failed_outbox >= settings.TASK_HEALTH_FAILED_OUTBOX_WARN_COUNT:
        issue(
            "OUTBOX_FAILED_PRESENT",
            "warning",
            "存在需要人工处理的 Outbox 永久失败任务。",
            failed_outbox,
        )

    severity = "ok"
    if any(item["severity"] == "error" for item in issues):
        severity = "error"
    elif issues:
        severity = "warning"

    return {"ok": severity != "error", "severity": severity, "issues": issues}

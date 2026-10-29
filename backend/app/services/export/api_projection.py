"""Export task response projection and pending-state diagnostics."""

from __future__ import annotations


def _task_to_response(task, *, ports):
    status_reason, status_message = pending_status_warning(task, ports=ports)
    now = ports("utcnow")()
    has_file = ports("bool")(
        task.file_key and (task.expires_at is None or task.expires_at > now)
    )
    response_status = (
        ports("ExportTaskStatus").EXPIRED
        if task.status == ports("ExportTaskStatus").COMPLETED
        and task.expires_at is not None
        and (task.expires_at <= now)
        else task.status
    )
    is_reexporting = ports("bool")(
        task.error_code == ports("REEXPORTING_ERROR_CODE")
        and task.status
        in (ports("ExportTaskStatus").PENDING, ports("ExportTaskStatus").PROCESSING)
    )
    reexport_failed = (
        task.error_code == ports("REEXPORT_FAILED_ERROR_CODE") and has_file
    )
    return build_task_response(
        task,
        response_status,
        status_reason,
        status_message,
        has_file,
        is_reexporting,
        reexport_failed,
        ports=ports,
    )


def pending_status_warning(task, *, ports):
    status_reason = None
    status_message = None
    if task.status == ports("ExportTaskStatus").PENDING:
        try:
            from app.services.export.processor import get_processor_health

            ph = get_processor_health()
            if not ph.get("running", False):
                status_reason = "processor_unavailable"
                status_message = "导出处理服务暂不可用，请稍后重试"
        except ports("Exception"):
            pass
        from app.core.config import settings as _export_settings
        from app.core.time_utils import utcnow as _utcnow

        if task.created_at:
            pending_seconds = (_utcnow() - task.created_at).total_seconds()
            warning_seconds = ports("getattr")(
                _export_settings, "EXPORT_PENDING_WARNING_SECONDS", 30
            )
            if pending_seconds > warning_seconds:
                if status_reason is None:
                    status_reason = "pending_timeout"
                    status_message = "等待时间较长，导出处理服务可能未启动"
                else:
                    status_message = "导出处理服务暂不可用，请稍后重试或联系管理员"
    return (status_reason, status_message)


def build_task_response(
    task,
    response_status,
    status_reason,
    status_message,
    has_file,
    is_reexporting,
    reexport_failed,
    *,
    ports,
):
    return ports("ExportTaskResponse")(
        id=task.id,
        status=response_status,
        file_format=task.file_format,
        file_name=task.file_name,
        file_size=task.file_size,
        title=task.title,
        range_type=task.range_type,
        sort_by=task.sort_by,
        group_by=task.group_by,
        answer_position=task.answer_position,
        analysis_position=task.analysis_position,
        space_style=task.space_style,
        total_count=task.total_count,
        success_count=task.success_count,
        skip_count=task.skip_count,
        error_message=task.error_message,
        status_reason=status_reason,
        status_message=status_message,
        created_at=task.created_at,
        completed_at=task.completed_at,
        expires_at=task.expires_at,
        source_task_id=task.source_task_id,
        retry_count=task.retry_count,
        generator_version=task.generator_version,
        has_file=has_file,
        is_reexporting=is_reexporting,
        reexport_failed=reexport_failed,
    )

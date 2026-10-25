"""Provider-failure response preserving an old force-regeneration cache."""

from __future__ import annotations

from collections.abc import Callable

from app.services.ai.analysis_responses import provider_failure_response


def build_provider_failure_response(
    *,
    wrong_question: object,
    requires_visual: bool,
    input_signature: str,
    model_signature: str,
    effective_force: bool,
    image_data_urls: list[str],
    cached_response: Callable[..., dict | None],
) -> Callable[..., dict]:
    def failure_response(
        *,
        error_code: str,
        retryable: bool,
        failure_model: str,
        duration_ms: int = 0,
    ) -> dict:
        old_cache = cached_response(
            wrong_question,
            requires_visual=requires_visual,
            expected_input_signature=input_signature,
            expected_model_signature=model_signature,
        )
        if effective_force and old_cache is not None:
            old_cache["force_regenerated"] = False
            old_cache["cache_preserved"] = True
            old_cache["error_code"] = error_code
            old_cache["retryable"] = retryable
            return old_cache
        return provider_failure_response(
            error_code=error_code,
            retryable=retryable,
            failure_model=failure_model,
            duration_ms=duration_ms,
            image_data_urls=image_data_urls,
        )

    return failure_response

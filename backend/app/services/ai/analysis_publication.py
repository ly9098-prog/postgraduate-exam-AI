"""Publish persisted analysis through synchronous logging and response ports."""


def publish_repaired_analysis(values: dict, *, namespace: dict) -> dict:
    values["logger"].warning(
        "ai.error_analysis.grounding_repaired wq_id=%s force=%s model=%s reason=%s expected=%s actual=%s",
        values["wrong_question"].id,
        values["effective_force"],
        values["result"].get("model"),
        values["grounding"].guard_reason,
        values["expected_answer_check"],
        values["grounding"].actual_answer_check,
    )
    return _port(namespace, "grounding_repaired_response")(
        content=values["safe"],
        tokens_used=values["usage"].total_tokens_used,
        duration_ms=values["usage"].total_duration_ms,
        effective_force=values["effective_force"],
        visual_input_count=_port(namespace, "len")(values["image_data_urls"]),
        visual_evidence=values["usage"].visual_evidence,
        generated_at=values["generated_at"],
    )


def publish_valid_analysis(values: dict, *, namespace: dict) -> dict:
    values["logger"].info(
        "ai.error_analysis.result wq_id=%s force=%s model=%s input_mode=%s visual_count=%s visual_evidence_valid=%s parsed_valid=%s compatibility=%s max_tokens=%s visual_ack_retried=%s visual_ack_retry_ms=%s fields=%s duration_ms=%s",
        values["wrong_question"].id,
        values["effective_force"],
        values["result"].get("model"),
        "vision" if values["image_data_urls"] else "text",
        _port(namespace, "len")(values["image_data_urls"]),
        values["visual_evidence_is_valid"](values["usage"].visual_evidence)
        if values["image_data_urls"]
        else None,
        True,
        values["result"].get("compatibility_profile") or "default",
        values["max_tokens"],
        values["usage"].visual_ack_retried,
        values["usage"].visual_ack_retry_ms,
        {
            k: _port(namespace, "bool")(values["parsed"].get(k))
            for k in ["mistake_diagnosis", "knowledge_patch", "review_task"]
        },
        values["usage"].total_duration_ms,
    )
    return _port(namespace, "valid_analysis_response")(
        values["parsed"],
        values["result"],
        tokens_used=values["usage"].total_tokens_used,
        duration_ms=values["usage"].total_duration_ms,
        effective_force=values["effective_force"],
        image_data_urls=values["image_data_urls"],
        visual_evidence=values["usage"].visual_evidence,
    )


def _port(namespace: dict, name: str):
    """Resolve original module globals and builtins at each expression site."""
    if name in namespace:
        return namespace[name]
    builtins = namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)

"""Result metadata and chat snapshot projection using historical live ports."""


def prepare_repaired_result(values: dict, *, namespace: dict) -> tuple[dict, str]:
    from app.ai.answer_grounding import build_safe_grounded_analysis

    safe = build_safe_grounded_analysis(values["answer_grounding"])
    generated_at = _port(namespace, "datetime").now(_port(namespace, "UTC")).isoformat()
    safe["_meta"] = _port(namespace, "_base_meta")(
        model="grounding_guard",
        source_model=values["result"].get("model", ""),
        runtime=values["runtime"],
        generated_at=generated_at,
        force_regenerated=values["effective_force"],
        visual_evidence=values["visual_evidence"],
        visual_ack_retried=values["visual_ack_retried"],
        visual_ack_retry_ms=values["visual_ack_retry_ms"],
        image_count=values["image_count"],
        input_signature=values["input_signature"],
        model_signature=values["model_signature"],
        expected_answer_check=values["expected_answer_check"],
    )
    safe["_meta"]["grounding_guard"] = "repaired"
    safe["_meta"]["grounding_guard_reason"] = values["grounding_guard_reason"]
    return (safe, generated_at)


def prepare_valid_result(values: dict, *, namespace: dict) -> None:
    values["parsed"]["mistake_diagnosis"] = _port(
        namespace, "merge_grounded_diagnosis"
    )(values["answer_grounding"], values["parsed"].get("mistake_diagnosis", ""))
    values["parsed"]["_meta"] = _port(namespace, "_base_meta")(
        model=values["result"].get("model", ""),
        source_model="",
        runtime=values["runtime"],
        generated_at=_port(namespace, "datetime")
        .now(_port(namespace, "UTC"))
        .isoformat(),
        force_regenerated=values["effective_force"],
        visual_evidence=values["visual_evidence"],
        visual_ack_retried=values["visual_ack_retried"],
        visual_ack_retry_ms=values["visual_ack_retry_ms"],
        image_count=values["image_count"],
        input_signature=values["input_signature"],
        model_signature=values["model_signature"],
        expected_answer_check=values["expected_answer_check"],
    )
    values["parsed"]["_meta"]["grounding_guard"] = "passed"
    return None


def project_analysis_snapshot(values: dict, *, namespace: dict, repaired: bool) -> dict:
    snapshot = _port(namespace, "build_context_snapshot")(
        values["context"],
        image_count=values["image_count"],
        visual_evidence=values["visual_evidence"],
        visual_ack_retried=values["visual_ack_retried"],
        visual_ack_retry_ms=values["visual_ack_retry_ms"],
    )
    if repaired:
        snapshot["grounding_guard"] = {
            "status": "repaired",
            "reason": values["grounding_guard_reason"],
            "expected_answer_check": values["expected_answer_check"],
            "actual_answer_check": values["actual_answer_check"],
        }
    return snapshot


def _port(namespace: dict, name: str):
    """Use the original module's globals and builtins, including missing-name errors."""
    if name in namespace:
        return namespace[name]
    builtins = namespace["__builtins__"]
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)

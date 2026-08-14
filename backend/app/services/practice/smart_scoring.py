"""Pure scoring and explanation primitives for smart practice recommendations.

Kept free of database access so scoring policy can be unit-tested independently
of candidate recall, vector search and fallback orchestration.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.question import Question
else:
    Question = Any

def _pick_graph_target_kps(
    kp_mastery: dict[int, tuple],
    *,
    limit: int = 5,
) -> list[int]:
    """Pick high-value weak KPs whose prerequisites are worth expanding.

    Low-confidence states are not treated as confirmed weakness.  This keeps
    the graph from turning an unobserved prerequisite into a hard learning
    detour while still allowing the graph helper to add a small diagnostic
    candidate for unknown *prerequisites* of a genuinely weak target.
    """
    ranked: list[tuple[int, float]] = []
    for kp_id, (mastery, confidence) in kp_mastery.items():
        mastery_value = 50.0 if mastery is None else mastery
        confidence_value = 0.0 if confidence is None else confidence
        mastery = max(0.0, min(float(mastery_value), 100.0))
        confidence = max(0.0, min(float(confidence_value), 1.0))
        if confidence < 0.3 or mastery >= 70.0:
            continue
        weakness = ((100.0 - mastery) / 100.0) * confidence
        ranked.append((kp_id, weakness))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [kp_id for kp_id, _score in ranked[:limit]]


def _get_observed_weak_kp_ids(
    kp_ids: list[int],
    kp_mastery: dict[int, tuple],
    kp_observations: dict[int, tuple[int, int]] | None = None,
) -> list[int]:
    """Return KPs with an early but meaningful weak-performance signal.

    This is intentionally weaker than ``weak_kp``: two or more attempts with
    at least two wrong answers and mastery <= 40 are enough to say that recent
    performance needs more validation, but not enough to declare a confirmed
    weakness. ``calculate_smart_score`` only emits this signal when the
    existing confirmed-weakness threshold has not been reached.
    """
    kp_observations = kp_observations or {}
    observed: list[int] = []
    for kp_id in kp_ids:
        mastery, _confidence = kp_mastery.get(kp_id, (50.0, 0.0))
        attempt_count, wrong_count = kp_observations.get(kp_id, (0, 0))
        mastery_value = 50.0 if mastery is None else float(mastery)
        if int(attempt_count or 0) >= 2 and int(wrong_count or 0) >= 2 and mastery_value <= 40.0:
            observed.append(kp_id)
    return observed


def _build_smart_recommendation_reason(
    reason_codes: list[str],
    kp_ids: list[int],
    kp_names: dict[int, str],
    graph_candidates: dict[int, dict] | None = None,
    blocked_kps: dict[int, list[dict]] | None = None,
    kp_mastery: dict[int, tuple] | None = None,
    kp_observations: dict[int, tuple[int, int]] | None = None,
) -> str:
    """Convert internal score reason codes into a concise combined Chinese reason.

    The explanation keeps the strongest recommendation signal as the main
    reason, then appends at most one useful secondary signal.  In particular,
    ``new_question`` is treated as supporting context instead of masking a more
    meaningful reason such as weak knowledge, review due, or wrong history.
    """
    graph_candidates = graph_candidates or {}
    blocked_kps = blocked_kps or {}
    kp_mastery = kp_mastery or {}
    kp_observations = kp_observations or {}
    reason_set = set(reason_codes)
    is_new = "new_question" in reason_set
    is_diverse = "diversity" in reason_set
    is_long_unpracticed = "long_unpracticed" in reason_set
    has_wrong_history = "wrong_history" in reason_set

    def _first_kp_name() -> str | None:
        return next((kp_names.get(k) for k in kp_ids if kp_names.get(k)), None)

    def _first_observed_weak_kp_name() -> str | None:
        observed_ids = _get_observed_weak_kp_ids(kp_ids, kp_mastery, kp_observations)
        return next((kp_names.get(k) for k in observed_ids if kp_names.get(k)), None)

    def _append_new_context(text: str) -> str:
        if not is_new:
            return text
        return f"{text} 同时推荐一道尚未练过的新题，用来检验当前掌握情况。"

    # Highest-value explanation: this question is a prerequisite selected to
    # repair a known weakness in another target KP.
    for kp_id in kp_ids:
        graph = graph_candidates.get(kp_id)
        if not graph:
            continue
        kp_name = graph.get("name") or kp_names.get(kp_id) or "这个知识点"
        origin_name = graph.get("origin_name") or "目标知识点"
        if graph.get("confirmed_gap"):
            return _append_new_context(
                f"你在「{origin_name}」上的掌握较弱，而「{kp_name}」是它的重要前置知识，建议先巩固「{kp_name}」。"
            )
        base = f"「{kp_name}」是「{origin_name}」的前置知识，目前掌握数据较少，这道题可用于快速确认基础是否扎实。"
        if is_new:
            return f"{base[:-1]}，并通过一道尚未练过的新题减少熟题记忆带来的干扰。"
        return base

    if "due_review" in reason_set:
        if has_wrong_history:
            return "这道题已进入复习窗口，而且你之前在这类题目上出现过错误，现在重做有助于巩固记忆并确认是否已经掌握。"
        return "这道题已进入复习窗口，现在练习有助于巩固记忆。"

    if "weak_kp" in reason_set:
        name = _first_kp_name()
        if name:
            if is_new:
                return f"你最近在「{name}」上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。"
            if has_wrong_history:
                return f"你最近在「{name}」上的掌握度较低，而且之前在相关题目上出现过错误，建议继续巩固。"
            return f"你最近在「{name}」上的掌握度较低，这道题适合继续巩固。"
        if is_new:
            return "你最近在这类知识点上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。"
        if has_wrong_history:
            return "你最近在这类知识点上的掌握度较低，而且之前在相关题目上出现过错误，建议继续巩固。"
        return "你最近在这类知识点上的掌握度较低，建议继续巩固。"

    if "observed_weak" in reason_set:
        name = _first_observed_weak_kp_name() or _first_kp_name()
        if name:
            if is_new:
                return f"你近期在「{name}」上的练习表现有待提升，推荐一道尚未练过的新题继续巩固并确认掌握情况。"
            if has_wrong_history:
                return f"你近期在「{name}」上的练习表现有待提升，而且之前在相关题目上出现过错误，建议继续巩固并确认掌握情况。"
            return f"你近期在「{name}」上的练习表现有待提升，这道题适合继续巩固并确认掌握情况。"
        if is_new:
            return "你近期在相关知识点上的练习表现有待提升，推荐一道尚未练过的新题继续巩固并确认掌握情况。"
        return "你近期在相关知识点上的练习表现有待提升，建议继续巩固并确认掌握情况。"

    if has_wrong_history:
        if is_long_unpracticed:
            return "你之前在这类题目上出现过错误，而且已有一段时间没有练习，建议现在重做确认是否已经掌握。"
        return "你之前在这类题目上出现过错误，建议再次练习确认是否已经掌握。"

    # A blocked target can still surface because it is overdue or has strong
    # historical signals.  Explain it honestly instead of exposing internal
    # tokens such as weak_prerequisite.
    for kp_id in kp_ids:
        blockers = blocked_kps.get(kp_id) or []
        if blockers:
            target_name = kp_names.get(kp_id) or "当前知识点"
            prereq_name = blockers[0].get("name") or "前置知识"
            return _append_new_context(
                f"「{target_name}」仍需巩固，同时「{prereq_name}」这一前置知识也较薄弱，建议结合练习。"
            )

    if "path_ready" in reason_set:
        name = _first_kp_name()
        if name:
            if is_new:
                return f"相关前置知识已经基本具备，可以继续巩固「{name}」；这道新题可用于检验能否顺利推进。"
            return f"相关前置知识已经基本具备，可以继续巩固「{name}」。"

    if is_new:
        if is_diverse:
            return "这是一道尚未练过的新题，同时用于补充近期练习的知识覆盖，检验当前掌握情况。"
        return "这是一道尚未练过的新题，用来检验当前掌握情况。"

    if is_long_unpracticed:
        if is_diverse:
            return "这个知识点已有一段时间没有练习，同时近期覆盖较少，适合现在做一次巩固。"
        return "这个知识点已有一段时间没有练习，适合现在做一次巩固。"

    if is_diverse:
        return "为避免重复刷同类题，这道题用于补充近期练习的知识覆盖。"

    return "根据你的近期答题表现和知识掌握情况推荐。"


def calculate_smart_score(
    question: Question,
    q_state,          # UserQuestionState | None
    kp_ids: list[int],
    kp_mastery: dict[int, tuple],   # kp_id -> (mastery_score, confidence)
    recent_kp_ids: set[int],
    now: datetime,
    kp_observations: dict[int, tuple[int, int]] | None = None,  # kp_id -> (attempt_count, wrong_count)
    blocked_kps: dict[int, list[dict]] | None = None,  # V6.3: kp_id -> [weak prereqs]
    graph_candidates: dict[int, dict] | None = None,  # V6.5: prereq kp -> graph context
    prerequisites_by_target: dict[int, list[dict]] | None = None,
    weights: dict[str, float] | None = None,  # 系统级 × 用户级综合权重
    graph_config: dict | None = None,
) -> tuple[float, list[str]]:
    """V4 综合打分 + V6.5 图谱候选扩展 + V6.4 权重个性化。

    维度:
      1. due_score        — 复习到期 (+40)         × due_weight
      2. overdue_score    — 逾期天数 (+2/天, max 20) × due_weight
      3. weakness_score   — 知识点薄弱              × weakness_weight
         observed_weak    — 低置信度弱势迹象 (+12)   × weakness_weight
      4. wrong_history    — 错题历史 (+8/次, max 30) × wrong_weight
      5. new_question     — 新题 (+20)              × new_question_weight
      6. long_unpracticed — 长期未练                × diversity_weight
      7. diversity        — 知识点多样性 (+10)       × diversity_weight
      8. path_blocked     — 前置知识点薄弱 (最多 -25) × path_weight
      9. prerequisite_need— 推荐薄弱前置 (最多 +45)   × path_weight
     10. path_ready       — 前置已满足可推进 (+8)      × path_weight
    """
    reasons: list[str] = []

    # 分组计分
    due_total = 0.0
    weakness_total = 0.0
    wrong_total = 0.0
    new_total = 0.0
    diversity_total = 0.0
    path_total = 0.0

    graph_config = graph_config or {}
    kp_observations = kp_observations or {}
    prerequisite_mastery_threshold = max(
        1.0, min(float(graph_config.get("prerequisite_mastery_threshold", 60.0)), 100.0)
    )
    prerequisite_confidence_threshold = max(
        0.0, min(float(graph_config.get("prerequisite_confidence_threshold", 0.3)), 1.0)
    )

    # ── 1 & 2: 到期复习 + 逾期 ──
    if q_state and q_state.next_review_at and q_state.next_review_at <= now:
        due_total += 40
        reasons.append("due_review")
        overdue_days = (now - q_state.next_review_at).days
        overdue_score = min(overdue_days * 2, 20)
        due_total += overdue_score
        if overdue_score > 0:
            reasons.append(f"overdue_{overdue_days}d")

    # ── 3: 知识点薄弱 ──
    if kp_ids:
        total_ws = 0.0
        cnt = 0
        for kid in kp_ids:
            ms, conf = kp_mastery.get(kid, (50.0, 0.0))
            total_ws += (100 - ms) * conf * 0.4
            cnt += 1
        if cnt:
            ws = total_ws / cnt
            weakness_total += ws
            if ws >= 15:
                reasons.append("weak_kp")
            else:
                observed_weak_kp_ids = _get_observed_weak_kp_ids(
                    kp_ids, kp_mastery, kp_observations
                )
                if observed_weak_kp_ids:
                    # Early-stage users often spread a small number of attempts
                    # across many KPs. Give repeated poor performance a medium
                    # bonus so related new questions can outrank generic new
                    # questions, without prematurely declaring a confirmed weak KP.
                    weakness_total += 12.0
                    reasons.append("observed_weak")

    # ── 4: 错题历史 ──
    if q_state:
        ws = min(q_state.wrong_count * 8, 30)
        wrong_total += ws
        if q_state.wrong_count > 0:
            reasons.append("wrong_history")

    # ── 5: 新题 ──
    if not q_state or q_state.answer_count == 0:
        new_total += 20
        reasons.append("new_question")

    # ── 6: 长期未练 ──
    if q_state and q_state.last_answered_at:
        days_since = (now - q_state.last_answered_at).days
        if days_since >= 30:
            ls = min(days_since * 0.5, 15)
            diversity_total += ls
            reasons.append("long_unpracticed")

    # ── 7: 知识点多样性 ──
    if kp_ids and not set(kp_ids) & recent_kp_ids:
        diversity_total += 10
        reasons.append("diversity")

    # ── 8~10: 知识点路径感知 (V6.5) ──
    if blocked_kps is not None and kp_ids:
        has_blocked = False
        blocked_quality = 0.0
        for kid in kp_ids:
            blockers = blocked_kps.get(kid) or []
            if blockers:
                has_blocked = True
                blocked_quality = max(
                    blocked_quality,
                    max(float(b.get("path_quality") or 0.0) for b in blockers),
                )
        if has_blocked:
            # Low-confidence / low-weight edges should only have a small
            # influence; graph data is weighted evidence, not an absolute rule.
            path_total -= 25 * blocked_quality
            reasons.append("weak_prerequisite")

    if graph_candidates and kp_ids:
        best_bonus = 0.0
        for kid in kp_ids:
            graph = graph_candidates.get(kid)
            if not graph:
                continue
            path_quality = max(0.0, min(float(graph.get("path_quality") or 0.0), 1.0))
            raw_origin_mastery = graph.get("origin_mastery_score")
            raw_origin_conf = graph.get("origin_mastery_confidence")
            raw_prereq_mastery = graph.get("mastery_score")
            raw_prereq_conf = graph.get("mastery_confidence")
            origin_mastery = max(0.0, min(float(50.0 if raw_origin_mastery is None else raw_origin_mastery), 100.0))
            origin_conf = max(0.0, min(float(0.0 if raw_origin_conf is None else raw_origin_conf), 1.0))
            prereq_mastery = max(0.0, min(float(50.0 if raw_prereq_mastery is None else raw_prereq_mastery), 100.0))
            prereq_conf = max(0.0, min(float(0.0 if raw_prereq_conf is None else raw_prereq_conf), 1.0))

            origin_need = ((100.0 - origin_mastery) / 100.0) * origin_conf
            if graph.get("confirmed_gap"):
                prereq_gap = max(
                    0.0,
                    (prerequisite_mastery_threshold - prereq_mastery)
                    / prerequisite_mastery_threshold,
                ) * prereq_conf
                bonus = 45.0 * (0.55 + 0.45 * origin_need) * (0.65 + 0.35 * prereq_gap) * path_quality
            else:
                # Unknown prerequisite: diagnostic exploration only.  Never let
                # it dominate a confirmed weakness.
                bonus = 10.0 * (0.5 + 0.5 * origin_need) * path_quality
            best_bonus = max(best_bonus, bonus)

        if best_bonus > 0:
            path_total += best_bonus
            reasons.append("prerequisite_need")

    if prerequisites_by_target and kp_ids and not any(k in (blocked_kps or {}) for k in kp_ids):
        # Only award "ready to progress" when the KP has direct prerequisites
        # and every one is sufficiently observed + mastered.  Unknown prereqs
        # are diagnostic candidates, not proof that the path is unlocked.
        for kid in kp_ids:
            direct_prereqs = [
                p for p in (prerequisites_by_target.get(kid) or [])
                if int(p.get("depth") or 0) == 1
            ]
            if direct_prereqs and all(
                not p.get("unknown_gap")
                and float(p.get("mastery_score") or 0.0) >= prerequisite_mastery_threshold
                and float(p.get("mastery_confidence") or 0.0) >= prerequisite_confidence_threshold
                for p in direct_prereqs
            ):
                path_total += 8
                reasons.append("path_ready")
                break

    # ── V6.4: 应用个性化权重 ──
    if weights:
        score = (
            due_total * weights.get("due_weight", 1.0)
            + weakness_total * weights.get("weakness_weight", 1.0)
            + wrong_total * weights.get("wrong_weight", 1.0)
            + new_total * weights.get("new_question_weight", 1.0)
            + diversity_total * weights.get("diversity_weight", 1.0)
            + path_total * weights.get("path_weight", 1.0)
        )
    else:
        score = due_total + weakness_total + wrong_total + new_total + diversity_total + path_total

    return score, reasons


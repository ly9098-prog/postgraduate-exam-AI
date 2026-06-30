from datetime import date, datetime, timedelta
import re

import logging
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_import import QuestionImport  # noqa: F401 — ensures Subject mapper resolves
from app.services.admin_subject_service import resolve_subject_ids
from app.services.behavior_service import record_answer_behavior
from app.services.wrong_question_service import record_wrong
from app.core.time_utils import utcnow

logger = logging.getLogger(__name__)


async def get_practice_subject_tree(db: AsyncSession) -> list[dict]:
    """返回刷题页可用科目树。

    数据来源：subjects 表中 is_active=true 的记录。
    使用 parent_id 构建树，按 sort_order, id 排序。
    不硬编码任何 subject_id。
    """
    from app.models.admin import Subject

    result = await db.execute(
        select(Subject)
        .where(Subject.is_active.is_(True))
        .order_by(Subject.sort_order.asc(), Subject.id.asc())
    )
    subjects = list(result.scalars().all())

    def _to_node(s: Subject) -> dict:
        return {
            "subject_id": s.id,
            "subject_code": s.code,
            "subject_name": s.name,
            "display_name": s.name,
            "level": s.level,
            "sort_order": s.sort_order,
            "children": [],
        }

    nodes: dict[int, dict] = {s.id: _to_node(s) for s in subjects}
    roots: list[dict] = []
    for s in subjects:
        node = nodes[s.id]
        parent = nodes.get(s.parent_id) if s.parent_id else None
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


async def resolve_subject_id_to_code(db: AsyncSession, subject_id: int) -> tuple[str, str] | None:
    """将 subject_id 解析为 (subject_code, subject_name)。不存在返回 None。"""
    from app.models.admin import Subject

    subj = await db.get(Subject, subject_id)
    if subj is None:
        return None
    return (subj.code, subj.name)


_TRUE_FALSE_TRUE = {"a", "true", "对", "是", "正确", "t", "yes", "1"}
_TRUE_FALSE_FALSE = {"b", "false", "错", "否", "错误", "f", "no", "0"}


def _normalize_true_false_answer(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in _TRUE_FALSE_TRUE:
        return "A"
    if v in _TRUE_FALSE_FALSE:
        return "B"
    return v.upper()


def _normalize_blank_choice_answer(value: str) -> dict[str, str]:
    result = {}
    for part in re.split(r"[;；,，\n]+", str(value or "")):
        match = re.match(r"^(.+?)\s*[:：=]\s*([A-Za-z])\s*$", part.strip())
        if match:
            result[match.group(1).strip()] = match.group(2).upper()
    return result


def _is_multi_blank_answer_correct(user_answer: str, correct_answer: str) -> bool:
    correct_map = _normalize_blank_choice_answer(correct_answer)
    if not correct_map:
        return False
    return _normalize_blank_choice_answer(user_answer) == correct_map


async def get_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject: str,
    count: int = 20,
    mode: str = "random",
    knowledge_points: list[str] | None = None,
    exclude_answered: bool = False,
) -> list[Question]:
    # 精确匹配子科目，或前缀匹配父科目（exam408 → exam408、exam408-ds、exam408-os …）
    ids = await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(ids)
    conditions = [Question.is_active == True, subject_cond]

    if knowledge_points:
        for kp in knowledge_points:
            conditions.append(Question.knowledge_points.like(f'%"{kp}"%'))

    if exclude_answered:
        answered_sub = (
            select(PracticeRecord.question_id)
            .where(PracticeRecord.user_id == user_id)
            .distinct()
        )
        conditions.append(Question.id.notin_(answered_sub))

    q = select(Question).where(and_(*conditions)).options(selectinload(Question.subject_ref))

    if mode == "random":
        q = q.order_by(func.random())
    else:
        q = q.order_by(Question.id.asc())

    q = q.limit(count)
    result = await db.execute(q)
    questions = list(result.scalars().all())

    logger.info(
        "[Practice Query] subject=%s mode=%s count=%d resultCount=%d",
        subject, mode, count, len(questions),
    )
    return questions


async def get_similar_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject: str,
    source_question_id: int,
    count: int = 20,
    exclude_answered: bool = False,
) -> tuple[list[Question], dict[int, dict]]:
    """similar 模式：基于源题的向量相似题召回，不足时用规则 + 随机补齐。

    返回: (questions_list, metadata_dict)
        metadata_dict: {question_id: {"recommend_reason": ..., "recommend_score": ..., "strategy": ..., "similarity": ...}}
    """
    metadata: dict[int, dict] = {}

    # 1. 向量召回
    vector_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service

        result = await vector_retrieval_service.search_similar_questions(
            db=db,
            user_id=user_id,
            question_id=source_question_id,
            count=count,
            exclude_answered=exclude_answered,
        )
        if result.get("enabled") and result.get("recommendations"):
            rec_ids = [r["question_id"] for r in result["recommendations"]]
            if rec_ids:
                q_result = await db.execute(
                    select(Question).where(Question.id.in_(rec_ids), Question.is_active == True).options(selectinload(Question.subject_ref))
                )
                q_map = {q.id: q for q in q_result.scalars().all()}
                for rec in result["recommendations"]:
                    q = q_map.get(rec["question_id"])
                    if q:
                        vector_questions.append(q)
                        metadata[q.id] = {
                            "recommend_reason": rec.get("match_reason", "向量相似"),
                            "recommend_score": rec.get("recommend_score"),
                            "strategy": "vector",
                            "similarity": rec.get("similarity"),
                        }
    except Exception:
        logger.warning("similar 模式向量召回失败，回退到随机", exc_info=True)

    if len(vector_questions) >= count:
        return vector_questions[:count], metadata

    # 2. 补齐：规则推荐 + 随机
    existing_ids = {q.id for q in vector_questions}
    existing_ids.add(source_question_id)

    ids = await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(ids)
    conditions = [
        Question.is_active == True,
        subject_cond,
        Question.id.notin_(existing_ids),
    ]
    if exclude_answered:
        answered_sub = (
            select(PracticeRecord.question_id)
            .where(PracticeRecord.user_id == user_id)
            .distinct()
        )
        conditions.append(Question.id.notin_(answered_sub))

    need = count - len(vector_questions)
    q = select(Question).where(and_(*conditions)).options(selectinload(Question.subject_ref)).order_by(func.random()).limit(need)
    result = await db.execute(q)
    fill_questions = list(result.scalars().all())

    for fq in fill_questions:
        metadata[fq.id] = {
            "recommend_reason": "规则补齐",
            "recommend_score": None,
            "strategy": "fallback",
            "similarity": None,
        }

    return vector_questions + fill_questions, metadata


async def get_smart_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject: str,
    count: int = 20,
    exclude_answered: bool = False,
    request_id: str | None = None,
    smart_strategy: str = "weakness_vector",
) -> tuple[list[Question], dict[int, dict]]:
    """smart 模式：基于薄弱知识点构造 query_text 进行向量召回，不足时补齐。

    Phase 3: 新增 smart_strategy="path" 知识路径推荐策略。
    Phase 2: 优先使用 UserKnowledgeState 画像，fallback 到近 30 天 PracticeRecord 统计。
    返回: (questions_list, metadata_dict)
    """
    metadata: dict[int, dict] = {}

    # Phase 4: 实验策略解析（best-effort）
    experiment_info = {
        "experiment_id": None,
        "variant_key": None,
        "strategy_config_id": None,
    }
    try:
        from app.services import recommendation_experiment_service

        resolved = await recommendation_experiment_service.resolve_strategy_for_user(
            db=db,
            user_id=user_id,
            scene="practice_smart",
            default_strategy=smart_strategy,
        )
        if resolved.get("source") == "experiment" and resolved.get("strategy"):
            smart_strategy = resolved["strategy"]
            experiment_info["experiment_id"] = resolved.get("experiment_id")
            experiment_info["variant_key"] = resolved.get("variant_key")
    except Exception:
        logger.warning("实验策略解析失败，使用默认策略", exc_info=True)

    # Phase 3: 知识路径策略
    if smart_strategy == "path":
        try:
            from app.services import knowledge_path_service

            path_result = await knowledge_path_service.get_user_path_recommendations(
                db=db,
                user_id=user_id,
                subject=subject,
                limit=8,
                questions_per_node=3,
            )
            path_qids = path_result.get("recommended_question_ids", [])
            if path_qids:
                # 获取题目
                q_result = await db.execute(
                    select(Question).where(
                        Question.id.in_(path_qids[:count]),
                        Question.is_active == True,
                    ).options(selectinload(Question.subject_ref))
                )
                q_map = {q.id: q for q in q_result.scalars().all()}
                # 保持 path_qids 的顺序（按优先级排序）
                path_questions = [q_map[qid] for qid in path_qids[:count] if qid in q_map]

                # 构建 metadata
                node_map = {}
                for node in path_result.get("nodes", []):
                    for qid in node.get("recommended_question_ids", []):
                        node_map[qid] = node

                for q in path_questions:
                    node = node_map.get(q.id, {})
                    metadata[q.id] = {
                        "recommend_reason": node.get("reason", f"知识路径推荐：{node.get('name', '')}"),
                        "recommend_score": node.get("priority"),
                        "strategy": "knowledge_path",
                        "similarity": None,
                    }

                if len(path_questions) >= count:
                    return await _finalize_smart(
                        path_questions[:count], metadata, db, user_id, subject,
                        request_id=request_id,
                        experiment_id=experiment_info.get("experiment_id"),
                        variant_key=experiment_info.get("variant_key"),
                    )

                # 不足时 fallback 到 weakness_vector
                logger.info("path 策略题量不足 (%d/%d)，fallback 到 weakness_vector",
                            len(path_questions), count)
                remaining = count - len(path_questions)
                fallback_questions, fallback_meta = await _smart_weakness_vector(
                    db, user_id, subject, count=remaining,
                    exclude_answered=exclude_answered,
                    exclude_ids={q.id for q in path_questions},
                )
                path_questions.extend(fallback_questions)
                metadata.update(fallback_meta)
                return await _finalize_smart(
                    path_questions[:count], metadata, db, user_id, subject,
                    request_id=request_id,
                    experiment_id=experiment_info.get("experiment_id"),
                    variant_key=experiment_info.get("variant_key"),
                )
        except Exception:
            logger.warning("knowledge_path 策略失败，fallback 到 weakness_vector", exc_info=True)
        # path 策略完全失败，继续走 weakness_vector 逻辑

    # 1. 获取薄弱知识点（Phase 2 优先使用掌握度画像）
    weak_kps: list[dict] = []
    weak_source = "unknown"
    try:
        from app.services import mastery_service
        weak_kps = await mastery_service.get_user_weak_knowledge_points(
            db, user_id, subject, limit=5,
        )
        if weak_kps:
            weak_source = "knowledge_state"
    except Exception:
        logger.warning("mastery_service.get_user_weak_knowledge_points failed, fallback", exc_info=True)

    if not weak_kps:
        # Fallback: Phase 1 的临时统计
        weak_kps = await _compute_weak_knowledge_points(db, user_id, subject)
        if weak_kps:
            weak_source = "practice_record"

    if not weak_kps:
        # 没有足够的做题记录来判断薄弱点，退化为随机
        logger.info("smart 模式: 无足够做题记录，退化为随机")
        questions = await get_practice_questions(
            db=db, user_id=user_id, subject=subject, count=count,
            mode="random", exclude_answered=exclude_answered,
        )
        for q in questions:
            metadata[q.id] = {
                "recommend_reason": "随机推荐（无足够做题记录）",
                "recommend_score": None,
                "strategy": "random_fallback",
                "similarity": None,
            }
        return await _finalize_smart(questions, metadata, db, user_id, subject,
                                     request_id=request_id,
                                     experiment_id=experiment_info.get("experiment_id"),
                                     variant_key=experiment_info.get("variant_key"))

    # 2. 构造 query_text 并向量召回
    kp_names = [kp["name"] for kp in weak_kps[:5]]
    query_text = (
        f"科目：{subject}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    vector_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service

        recalls = await vector_retrieval_service.vector_recall_by_text(
            db=db,
            user_id=user_id,
            subject=subject,
            query_text=query_text,
            count=count,
            exclude_answered=exclude_answered,
        )
        if recalls:
            rec_ids = [r["question_id"] for r in recalls]
            q_result = await db.execute(
                select(Question).where(Question.id.in_(rec_ids), Question.is_active == True).options(selectinload(Question.subject_ref))
            )
            q_map = {q.id: q for q in q_result.scalars().all()}
            for rec in recalls:
                q = q_map.get(rec["question_id"])
                if q:
                    vector_questions.append(q)
                    metadata[q.id] = {
                        "recommend_reason": f"薄弱知识点推荐：{'、'.join(kp_names[:3])}",
                        "recommend_score": rec.get("recommend_score"),
                        "strategy": "smart_vector",
                        "similarity": rec.get("similarity"),
                    }
    except Exception:
        logger.warning("smart 模式向量召回失败，回退", exc_info=True)

    if len(vector_questions) >= count:
        return await _finalize_smart(vector_questions[:count], metadata, db, user_id, subject,
                                     request_id=request_id,
                                     experiment_id=experiment_info.get("experiment_id"),
                                     variant_key=experiment_info.get("variant_key"))

    # 3. 补齐：按薄弱知识点过滤 + 随机
    existing_ids = {q.id for q in vector_questions}
    ids = await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(ids)
    conditions = [
        Question.is_active == True,
        subject_cond,
        Question.id.notin_(existing_ids),
    ]
    if exclude_answered:
        answered_sub = (
            select(PracticeRecord.question_id)
            .where(PracticeRecord.user_id == user_id)
            .distinct()
        )
        conditions.append(Question.id.notin_(answered_sub))

    # 优先按薄弱知识点过滤
    if kp_names:
        kp_conditions = []
        for kp in kp_names:
            kp_conditions.append(Question.knowledge_points.like(f'%"{kp}"%'))
        kp_cond = or_(*kp_conditions)
        kp_q = select(Question).where(and_(*conditions, kp_cond)).options(selectinload(Question.subject_ref)).order_by(func.random())
        result = await db.execute(kp_q)
        kp_fill = list(result.scalars().all())

        for fq in kp_fill:
            if fq.id not in existing_ids:
                existing_ids.add(fq.id)
                vector_questions.append(fq)
                metadata[fq.id] = {
                    "recommend_reason": f"薄弱知识点补齐：{'、'.join(kp_names[:3])}",
                    "recommend_score": None,
                    "strategy": "kp_fallback",
                    "similarity": None,
                }
                if len(vector_questions) >= count:
                    break

    # 4. 最终随机补齐
    if len(vector_questions) < count:
        remaining = count - len(vector_questions)
        fill_q = (
            select(Question)
            .where(and_(*conditions, Question.id.notin_(existing_ids)))
            .options(selectinload(Question.subject_ref))
            .order_by(func.random())
            .limit(remaining)
        )
        result = await db.execute(fill_q)
        random_fill = list(result.scalars().all())

        for fq in random_fill:
            metadata[fq.id] = {
                "recommend_reason": "随机补齐",
                "recommend_score": None,
                "strategy": "random_fallback",
                "similarity": None,
            }
        vector_questions.extend(random_fill)

    return await _finalize_smart(vector_questions[:count], metadata, db, user_id, subject,
                                 request_id=request_id,
                                 experiment_id=experiment_info.get("experiment_id"),
                                 variant_key=experiment_info.get("variant_key"))


async def _finalize_smart(
    questions: list[Question],
    metadata: dict[int, dict],
    db: AsyncSession,
    user_id: int,
    subject: str,
    request_id: str | None = None,
    experiment_id: int | None = None,
    variant_key: str | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """smart 模式统一收尾：写推荐日志（best-effort），返回结果。"""
    try:
        from collections import Counter
        from app.services import recommendation_log_service

        recs = [
            {
                "question_id": qid,
                "subject": subject,
                "recommend_score": meta.get("recommend_score"),
                "similarity": meta.get("similarity"),
                "reason": meta.get("recommend_reason"),
            }
            for qid, meta in metadata.items()
        ]
        if recs:
            # 取出现最多的 strategy 而非仅第一条
            strategy_counts = Counter(
                meta.get("strategy", "fallback") for meta in metadata.values()
            )
            dominant_strategy = strategy_counts.most_common(1)[0][0]

            await recommendation_log_service.create_recommendation_logs(
                db=db,
                user_id=user_id,
                recommendations=recs,
                scene="practice_smart",
                strategy=dominant_strategy,
                request_id=request_id,
                experiment_id=experiment_id,
                variant_key=variant_key,
            )
    except Exception:
        logger.warning("smart 推荐日志写入失败（不影响结果）", exc_info=True)

    return questions, metadata


async def _smart_weakness_vector(
    db: AsyncSession,
    user_id: int,
    subject: str,
    count: int = 20,
    exclude_answered: bool = False,
    exclude_ids: set[int] | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """Phase 2 weakness_vector 策略：薄弱知识点 → 向量召回 → KP 补齐 → 随机补齐。

    供 smart_strategy="path" 的 fallback 复用。
    exclude_ids: 需要额外排除的题目 ID 集合（如 path 策略已选的题）。
    """
    exclude_ids = exclude_ids or set()
    metadata: dict[int, dict] = {}

    # 获取薄弱知识点
    weak_kps: list[dict] = []
    try:
        from app.services import mastery_service
        weak_kps = await mastery_service.get_user_weak_knowledge_points(
            db, user_id, subject, limit=5,
        )
    except Exception:
        logger.warning("mastery_service.get_user_weak_knowledge_points failed", exc_info=True)

    if not weak_kps:
        weak_kps = await _compute_weak_knowledge_points(db, user_id, subject)

    if not weak_kps:
        # 退化为随机
        questions = await get_practice_questions(
            db=db, user_id=user_id, subject=subject, count=count,
            mode="random", exclude_answered=exclude_answered,
        )
        for q in questions:
            if q.id not in exclude_ids:
                metadata[q.id] = {
                    "recommend_reason": "随机推荐（薄弱知识点数据不足）",
                    "recommend_score": None,
                    "strategy": "random_fallback",
                    "similarity": None,
                }
        return [q for q in questions if q.id not in exclude_ids], metadata

    kp_names = [kp["name"] for kp in weak_kps[:5]]
    query_text = (
        f"科目：{subject}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    result_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service
        recalls = await vector_retrieval_service.vector_recall_by_text(
            db=db, user_id=user_id, subject=subject,
            query_text=query_text, count=count,
            exclude_answered=exclude_answered,
        )
        if recalls:
            rec_ids = [r["question_id"] for r in recalls if r["question_id"] not in exclude_ids]
            if rec_ids:
                q_result = await db.execute(
                    select(Question).where(Question.id.in_(rec_ids), Question.is_active == True).options(selectinload(Question.subject_ref))
                )
                q_map = {q.id: q for q in q_result.scalars().all()}
                for rec in recalls:
                    q = q_map.get(rec["question_id"])
                    if q and q.id not in exclude_ids:
                        result_questions.append(q)
                        metadata[q.id] = {
                            "recommend_reason": f"薄弱知识点推荐：{'、'.join(kp_names[:3])}",
                            "recommend_score": rec.get("recommend_score"),
                            "strategy": "smart_vector",
                            "similarity": rec.get("similarity"),
                        }
    except Exception:
        logger.warning("weakness_vector 向量召回失败", exc_info=True)

    if len(result_questions) >= count:
        return result_questions[:count], metadata

    # 随机补齐
    existing_ids = {q.id for q in result_questions} | exclude_ids
    ids = await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(ids)
    conditions = [
        Question.is_active == True,
        subject_cond,
        Question.id.notin_(existing_ids),
    ]
    if exclude_answered:
        answered_sub = (
            select(PracticeRecord.question_id)
            .where(PracticeRecord.user_id == user_id)
            .distinct()
        )
        conditions.append(Question.id.notin_(answered_sub))

    remaining = count - len(result_questions)
    fill_q = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
        .order_by(func.random())
        .limit(remaining)
    )
    fill_result = await db.execute(fill_q)
    fill_questions = list(fill_result.scalars().all())
    for fq in fill_questions:
        metadata[fq.id] = {
            "recommend_reason": "薄弱知识点补齐",
            "recommend_score": None,
            "strategy": "kp_fallback",
            "similarity": None,
        }
    result_questions.extend(fill_questions)

    return result_questions[:count], metadata


async def _compute_weak_knowledge_points(
    db: AsyncSession, user_id: int, subject: str
) -> list[dict]:
    """计算薄弱知识点：最近 30 天，total >= 2 且 accuracy < 0.65。

    返回按 accuracy 升序、total 降序排列的前 5 个薄弱知识点。
    """
    cutoff = utcnow() - timedelta(days=30)
    subject_cond = or_(
        PracticeRecord.subject == subject,
        PracticeRecord.subject.like(f"{subject}-%"),
    )

    # 获取最近 30 天的做题记录，带题目的 knowledge_points
    result = await db.execute(
        select(PracticeRecord, Question.knowledge_points)
        .join(Question, PracticeRecord.question_id == Question.id)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= cutoff,
            subject_cond,
        )
    )
    rows = result.all()

    if not rows:
        return []

    # 按知识点聚合
    kp_stats: dict[str, dict] = {}
    for record, kps_json in rows:
        kps = kps_json or []
        for kp in kps:
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "correct": 0}
            kp_stats[kp]["total"] += 1
            if record.is_correct:
                kp_stats[kp]["correct"] += 1

    # 筛选薄弱知识点
    weak = []
    for kp_name, stats in kp_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        if total >= 2:
            accuracy = correct / total
            if accuracy < 0.65:
                weak.append({
                    "name": kp_name,
                    "total": total,
                    "correct": correct,
                    "accuracy": round(accuracy, 4),
                })

    # 按 accuracy 升序、total 降序
    weak.sort(key=lambda x: (x["accuracy"], -x["total"]))
    return weak[:5]


async def submit_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str,
    used_time: int | None = None,
    request_id: str | None = None,
) -> dict:
    result = await db.execute(
        select(Question).where(
            Question.id == question_id, Question.is_active == True
        )
    )
    question = result.scalar_one_or_none()
    if not question:
        raise ValueError(f"题目不存在: {question_id}")

    if question.question_type == "multi_blank_choice":
        is_correct = _is_multi_blank_answer_correct(user_answer, question.answer)
    elif question.question_type in ("true_false", "judgement"):
        is_correct = _normalize_true_false_answer(user_answer) == _normalize_true_false_answer(question.answer)
    else:
        is_correct = user_answer.strip().lower() == question.answer.strip().lower()

    record = PracticeRecord(
        user_id=user_id,
        question_id=question_id,
        subject=question.subject_ref.code if question.subject_ref else "",
        question_type=question.question_type,
        user_answer=user_answer.strip(),
        is_correct=is_correct,
        used_time=used_time,
        answered_at=utcnow(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # 答题后清理向量推荐缓存（best-effort，失败不影响核心流程）
    try:
        from app.services.vector_retrieval_service import invalidate_vector_cache
        await invalidate_vector_cache(user_id)
    except Exception:
        logger.debug("向量缓存清理失败（不影响答题）uid=%d", user_id, exc_info=True)

    # ── Phase 2: 最佳效果后置操作（不影响答题主流程）──
    # 以下全部在 db.commit() 之后执行，失败不影响核心数据
    is_wrong_added = False
    try:
        if not is_correct:
            await record_wrong(db, user_id, question_id, user_answer.strip())
            is_wrong_added = True
    except Exception:
        logger.warning("错题记录失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)
        await db.rollback()

    try:
        await record_answer_behavior(
            db=db,
            user_id=user_id,
            question_id=question_id,
            practice_record_id=record.id,
            time_spent_sec=used_time or 0,
            is_first_correct=is_correct,
            is_final_correct=is_correct,
            user_answer=user_answer.strip(),
            correct_answer=question.answer,
            subject=question.subject_ref.code if question.subject_ref else "",
            session_type="practice",
        )
    except Exception:
        logger.warning("答题行为记录失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)
        await db.rollback()

    # ── Phase 3: 掌握度更新 + 推荐反馈（best-effort）──
    try:
        from app.services import mastery_service
        await mastery_service.update_user_knowledge_state_after_answer(
            db, user_id, question_id, is_correct,
        )
    except Exception:
        logger.warning("掌握度更新失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)
        await db.rollback()

    try:
        from app.services import recommendation_log_service
        await recommendation_log_service.mark_recommendation_answered(
            db, user_id, question_id, is_correct, request_id=request_id,
        )
    except Exception:
        logger.warning("推荐日志标记失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)
        await db.rollback()

    return {
        "record_id": record.id,
        "question_id": question_id,
        "is_correct": is_correct,
        "correct_answer": question.answer,
        "analysis": question.analysis,
        "knowledge_points": question.knowledge_points or [],
        "is_wrong_added": is_wrong_added,
    }


async def batch_submit_answers(
    db: AsyncSession,
    user_id: int,
    answers: list[dict],
) -> dict:
    question_ids = [a["question_id"] for a in answers]
    result = await db.execute(
        select(Question).where(
            Question.id.in_(question_ids), Question.is_active == True
        )
    )
    questions = {q.id: q for q in result.scalars().all()}

    missing = [qid for qid in question_ids if qid not in questions]
    if missing:
        raise ValueError(f"题目不存在: {missing}")

    results = []
    total_correct = 0
    total_wrong = 0

    for a in answers:
        r = await submit_answer(
            db=db,
            user_id=user_id,
            question_id=a["question_id"],
            user_answer=a.get("user_answer", a.get("answer", "")),
            used_time=a.get("used_time"),
            request_id=a.get("request_id"),
        )
        results.append(r)
        if r["is_correct"]:
            total_correct += 1
        else:
            total_wrong += 1

    return {
        "results": results,
        "total_correct": total_correct,
        "total_wrong": total_wrong,
    }


async def get_practice_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    base = select(
        func.count(PracticeRecord.id),
        func.coalesce(
            func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
        ),
    ).where(PracticeRecord.user_id == user_id)

    total_row = (await db.execute(base)).one()
    total_answered = total_row[0]
    total_correct = total_row[1]
    accuracy = round(total_correct / total_answered, 4) if total_answered > 0 else 0.0

    # By subject
    subject_result = await db.execute(
        select(
            PracticeRecord.subject,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject)
    )
    by_subject = {}
    for row in subject_result.all():
        answered = row[1]
        correct = row[2]
        by_subject[row[0]] = {
            "answered": answered,
            "correct": correct,
            "accuracy": round(correct / answered, 4) if answered > 0 else 0.0,
        }

    # Daily stats
    since = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())
    daily_result = await db.execute(
        select(
            func.date(PracticeRecord.answered_at),
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(func.date(PracticeRecord.answered_at))
        .order_by(func.date(PracticeRecord.answered_at))
    )
    daily_map = {str(r[0]): {"answered": r[1], "correct": r[2]} for r in daily_result.all()}

    daily_stats = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        entry = daily_map.get(d, {"answered": 0, "correct": 0})
        daily_stats.append({"date": d, **entry})

    streak = await _calc_streak(db, user_id)

    return {
        "total_answered": total_answered,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "by_subject": by_subject,
        "daily_stats": daily_stats,
        "current_streak": streak,
    }


async def _calc_streak(db: AsyncSession, user_id: int) -> int:
    today = date.today()
    result = await db.execute(
        select(func.date(PracticeRecord.answered_at))
        .where(PracticeRecord.user_id == user_id)
        .distinct()
        .order_by(func.date(PracticeRecord.answered_at).desc())
    )
    dates = {row[0] for row in result.all()}

    streak = 0
    for i in range(365):
        d = today - timedelta(days=i)
        if d in dates:
            streak += 1
        else:
            break
    return streak


async def get_wrong_questions(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    from app.services.wrong_question_service import list_wrong

    items, total = await list_wrong(
        db, user_id, subject=subject, page=page, page_size=page_size
    )

    question_ids = [wq.question_id for wq in items]
    if question_ids:
        q_result = await db.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        q_map = {q.id: q for q in q_result.scalars().all()}
    else:
        q_map = {}

    wrong_list = []
    for wq in items:
        q = q_map.get(wq.question_id)
        wrong_list.append({
            "id": wq.id,
            "question_id": wq.question_id,
            "wrong_answer": wq.wrong_answer,
            "review_count": wq.review_count,
            "mastered": wq.mastered,
            "last_review_at": str(wq.last_review_at) if wq.last_review_at else None,
            "question": {
                "id": q.id,
                "subject": q.subject_ref.code if q.subject_ref else "",
                "question_type": q.question_type,
                "content": q.content,
                "options": q.options,
                "answer": q.answer,
                "analysis": q.analysis,
            } if q else None,
        })

    return {
        "items": wrong_list,
        "total": total,
        "page": page,
        "page_size": page_size,
    }

#!/usr/bin/env python3
"""backfill_knowledge_points_full.py — 将 questions.knowledge_points JSON 回填到关联表。

背景：`questions.knowledge_points` 是冗余 JSON 列，将在迁移中被删除。本脚本在删列前
把每道题的知识点写入 `knowledge_points` 主表 + `question_knowledge_points` 关联表
（带 position 保序），并做 fail-closed 门禁校验。

用法（生产服务器 app 容器内，先做 staging 演练）:
    python scripts/backfill_knowledge_points_full.py \
        --db-url="postgresql+asyncpg://postgraduate:***@postgres:5432/postgraduate_dryrun" \
        --expected-question-count=2165 --expected-kp-count=428 --expected-mapping-count=4374 \
        [--dry-run] [--verify-only]

参数:
    --db-url                   目标数据库 URL（默认用 env DATABASE_URL）。
    --dry-run                  只计算计划并跑"计划后状态"门禁，不写库。
    --verify-only              只对当前库状态跑门禁（用于写后复核），不写库。
    --expected-question-count  有知识点 JSON 的题目数门禁（默认不强制）。
    --expected-kp-count        回填后 knowledge_points 主表总数门禁。
    --expected-mapping-count   回填后 question_knowledge_points 总数门禁。

门禁 G1-G5（非 dry-run 任一失败 → 非 0 exit，单事务 rollback，部署据此中止删列）:
    G1  knowledge_points 总数
    G2  qkp 映射总数 / mapped questions
    G3a 逐题 mapped normalized 集合 == JSON normalized 集合（0 差异）
    G3b 逐题 API 可见有序 display 列表 == JSON trim 后（0 差异；唯一例外 qid=1050 重复 KP 折叠）
    G4  无孤儿映射
    G5  Question.subject_id == KnowledgePoint.subject_id 全部成立

输出不打印敏感连接串。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

logger = logging.getLogger("backfill_knowledge_points")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=None, help="目标数据库 URL（默认 env DATABASE_URL）")
    parser.add_argument("--dry-run", action="store_true", help="只计算计划，不写库")
    parser.add_argument("--verify-only", action="store_true", help="只对当前库跑门禁，不写库")
    parser.add_argument("--expected-question-count", type=int, default=None)
    parser.add_argument("--expected-kp-count", type=int, default=None)
    parser.add_argument("--expected-mapping-count", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url
    return args


def normalize_kp_input(kp_names):
    """trim → normalize → 按 normalized 去重（保留首次 display 与顺序）。"""
    from app.services.knowledge_point_service import normalize_knowledge_name

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in kp_names or []:
        if raw is None:
            continue
        display = str(raw).strip()
        if not display:
            continue
        norm = normalize_knowledge_name(display)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append((display, norm))
    return out


async def _load_state(db):
    """加载现有 KP 主表 + 映射 + 题目 JSON，返回用于计算的数据结构。"""
    from sqlalchemy import text

    kp_rows = (await db.execute(
        text("SELECT id, subject_id, normalized_name, name FROM knowledge_points")
    )).all()
    kp_by_key: dict[tuple[int, str], tuple[int, str]] = {
        (r[1], r[2]): (r[0], r[3]) for r in kp_rows
    }
    kp_by_id: dict[int, tuple[int, str]] = {r[0]: (r[1], r[3]) for r in kp_rows}

    map_rows = (await db.execute(
        text("SELECT question_id, knowledge_point_id, position FROM question_knowledge_points")
    )).all()
    map_by_q: dict[int, dict[int, int]] = {}
    for qid, kpid, pos in map_rows:
        map_by_q.setdefault(qid, {})[kpid] = pos

    q_rows = (await db.execute(
        text(
            "SELECT id, subject_id, knowledge_points::text FROM questions "
            "WHERE knowledge_points IS NOT NULL AND json_array_length(knowledge_points::json) > 0"
        )
    )).all()
    questions: list[dict] = []
    for qid, subject_id, kp_text in q_rows:
        try:
            raw = json.loads(kp_text)
        except Exception:
            logger.error("qid=%d JSON 解析失败: %s", qid, kp_text[:80])
            raise SystemExit(1)
        questions.append({"id": qid, "subject_id": subject_id, "raw": raw})

    return {
        "kp_by_key": kp_by_key,
        "kp_by_id": kp_by_id,
        "map_by_q": map_by_q,
        "questions": questions,
    }


def _build_plan(state):
    """计算每道题的目标 entries 与需要新建的 KP / 映射 / position 更新。

    返回 (plan, new_kps, diff)：
    - plan: list[{qid, subject_id, entries:[(display, norm)], kp_ids:[(kp_id, position)]}]
    - new_kps: list[(subject_id, display, norm)] 待插入主表
    - diff: {created_kps, created_mappings, updated_positions, duplicate_input_items, subject_mismatches}
    """
    kp_by_key = state["kp_by_key"]
    plan = []
    new_kps = []
    diff = {"created_kps": 0, "created_mappings": 0, "updated_positions": 0,
            "duplicate_input_items": 0, "subject_mismatches": 0}

    for q in state["questions"]:
        raw_trimmed = [str(x).strip() for x in q["raw"] if x is not None and str(x).strip()]
        entries = normalize_kp_input(raw_trimmed)
        # 题内重复项统计（原始输入，按 normalized 去重前）
        from app.services.knowledge_point_service import normalize_knowledge_name
        seen_norms: set[str] = set()
        for _x in raw_trimmed:
            n = normalize_knowledge_name(_x)
            if n in seen_norms:
                diff["duplicate_input_items"] += 1
            else:
                seen_norms.add(n)

        kp_ids: list[tuple[int, int]] = []
        for position, (display, norm) in enumerate(entries):
            key = (q["subject_id"], norm)
            kp = kp_by_key.get(key)
            if kp is None:
                # 先以负号预留占位，稍后统一建表后回填 id
                placeholder = -len(new_kps) - 1
                new_kps.append((q["subject_id"], display, norm, key))
                kp_by_key[key] = (placeholder, display)
                kp_ids.append((placeholder, position))
            else:
                kp_ids.append((kp[0], position))
        plan.append({
            "qid": q["id"], "subject_id": q["subject_id"],
            "entries": entries, "kp_ids": kp_ids, "raw_trimmed": raw_trimmed,
        })

    # 计算 diff（用占位 id 视作新建映射）
    for p in plan:
        existing = state["map_by_q"].get(p["qid"], {})
        for kp_id, position in p["kp_ids"]:
            if kp_id < 0:
                diff["created_mappings"] += 1
            elif existing.get(kp_id) != position:
                if kp_id in existing:
                    diff["updated_positions"] += 1
                else:
                    diff["created_mappings"] += 1
    diff["created_kps"] = len(new_kps)
    return plan, new_kps, diff


def _run_planned_gates(state, plan, diff, args) -> list[str]:
    """在"计划后状态"上跑 G1-G5，返回失败消息列表。"""
    from app.services.knowledge_point_service import normalize_knowledge_name

    failures: list[str] = []
    kp_by_id = state["kp_by_id"]
    # 合并占位新 KP
    all_kp_ids = set(kp_by_id.keys())
    for p in plan:
        for kp_id, _pos in p["kp_ids"]:
            if kp_id >= 0:
                all_kp_ids.add(kp_id)

    # G1: 主表总数
    total_kp = len(kp_by_id) + diff["created_kps"]
    if args.expected_kp_count is not None and total_kp != args.expected_kp_count:
        failures.append(f"G1 knowledge_points={total_kp} != expected {args.expected_kp_count}")

    # G2: 映射总数 + mapped questions
    total_mappings = 0
    mapped_q = 0
    for p in plan:
        total_mappings += len(p["kp_ids"])
        if p["kp_ids"]:
            mapped_q += 1
    # 无 JSON 但有历史映射的题也算 mapped（当前生产不存在该情况）
    has_json_qids = {p["qid"] for p in plan}
    for qid, existing in state["map_by_q"].items():
        if qid not in has_json_qids and existing:
            total_mappings += len(existing)
            mapped_q += 1
    if args.expected_mapping_count is not None and total_mappings != args.expected_mapping_count:
        failures.append(f"G2 mappings={total_mappings} != expected {args.expected_mapping_count}")
    if args.expected_question_count is not None and mapped_q != args.expected_question_count:
        failures.append(f"G2 mapped_questions={mapped_q} != expected {args.expected_question_count}")

    # G3a/G3b/G5: 逐题比对（含占位新 KP）
    g3b_exception_qids = {1050}  # 已知重复 KP 折叠题（uq_qkp_question_kp 强制去重）
    for p in plan:
        json_ordered = p["raw_trimmed"]
        json_norms = {norm for _d, norm in p["entries"]}
        by_pos: dict[int, str] = {}
        mapped_norms: set[str] = set()
        for kp_id, position in p["kp_ids"]:
            if kp_id < 0:
                display = p["entries"][position][0]
                norm = p["entries"][position][1]
            else:
                kp_subj, name = kp_by_id[kp_id]
                display = name
                norm = normalize_knowledge_name(name)
                if p["subject_id"] != kp_subj:
                    failures.append(f"G5 qid={p['qid']} subject mismatch q={p['subject_id']} kp={kp_subj}")
            by_pos[position] = display
            mapped_norms.add(norm)
        if json_norms != mapped_norms:
            failures.append(
                f"G3a qid={p['qid']} normalized set diff "
                f"json={sorted(json_norms)} mapped={sorted(mapped_norms)}"
            )
        mapped_ordered = [by_pos[i] for i in sorted(by_pos)]
        if p["qid"] in g3b_exception_qids:
            # 例外题：原始 JSON 有重复 KP，映射表唯一约束强制折叠为 1 条
            deduped = list(dict.fromkeys(json_ordered))
            if mapped_ordered != deduped:
                failures.append(
                    f"G3b qid={p['qid']} (approved exception) "
                    f"json={json_ordered} mapped={mapped_ordered}"
                )
        elif mapped_ordered != json_ordered:
            failures.append(
                f"G3b qid={p['qid']} ordered list diff json={json_ordered} mapped={mapped_ordered}"
            )

    # G4: 无孤儿（所有既有映射的 kp 在主表）
    for qid, existing in state["map_by_q"].items():
        for kpid in existing:
            if kpid not in kp_by_id:
                failures.append(f"G4 qid={qid} orphan kp_id={kpid}")

    return failures


async def _run_verify_only(db, args) -> int:
    """对当前库状态跑 G1-G5（不写库），用于写后复核。"""
    from app.services.knowledge_point_service import normalize_knowledge_name

    state = await _load_state(db)
    failures: list[str] = []
    kp_by_id = state["kp_by_id"]
    map_by_q = state["map_by_q"]

    if args.expected_kp_count is not None and len(kp_by_id) != args.expected_kp_count:
        failures.append(f"G1 knowledge_points={len(kp_by_id)} != expected {args.expected_kp_count}")
    total_mappings = sum(len(v) for v in map_by_q.values())
    mapped_q = len(map_by_q)
    if args.expected_mapping_count is not None and total_mappings != args.expected_mapping_count:
        failures.append(f"G2 mappings={total_mappings} != expected {args.expected_mapping_count}")
    if args.expected_question_count is not None and mapped_q != args.expected_question_count:
        failures.append(f"G2 mapped_questions={mapped_q} != expected {args.expected_question_count}")

    for q in state["questions"]:
        raw_trimmed = [str(x).strip() for x in q["raw"] if x is not None and str(x).strip()]
        entries = normalize_kp_input(raw_trimmed)
        existing = map_by_q.get(q["id"], {})
        mapped_names = []
        subject_ok = True
        for kpid, pos in sorted(existing.items(), key=lambda kv: kv[1]):
            if kpid not in kp_by_id:
                failures.append(f"G4 qid={q['id']} orphan kp_id={kpid}")
                continue
            kp_subj, name = kp_by_id[kpid]
            mapped_names.append((pos, name))
            if kp_subj != q["subject_id"]:
                subject_ok = False
        if not subject_ok:
            failures.append(f"G5 qid={q['id']} subject mismatch")
        mapped_ordered = [n for _pos, n in sorted(mapped_names)]
        json_norms = {n for _d, n in entries}
        mapped_norms = {normalize_knowledge_name(n) for _pos, n in mapped_names}
        if json_norms != mapped_norms:
            failures.append(f"G3a qid={q['id']} normalized set diff")
        if q["id"] == 1050:
            deduped = list(dict.fromkeys(raw_trimmed))
            if mapped_ordered != deduped:
                failures.append(f"G3b qid=1050 (approved exception) json={raw_trimmed} mapped={mapped_ordered}")
        elif mapped_ordered != raw_trimmed:
            failures.append(f"G3b qid={q['id']} ordered list diff json={raw_trimmed} mapped={mapped_ordered}")

    for line in failures:
        logger.error("  ✗ %s", line)
    if failures:
        logger.error("verify: FAILED (%d)", len(failures))
        return 1
    logger.info("verify: ALL GATES PASS (kp=%d mappings=%d mapped_q=%d)",
                len(kp_by_id), total_mappings, mapped_q)
    return 0


async def run(args) -> int:
    from sqlalchemy import text

    from app.core.database import async_session
    from app.models.knowledge_point import KnowledgePoint
    from app.models.question_knowledge_point import QuestionKnowledgePoint

    async with async_session() as db:
        if args.verify_only:
            return await _run_verify_only(db, args)

        state = await _load_state(db)
        plan, new_kps, diff = _build_plan(state)

        if args.dry_run:
            print(f"[dry-run] questions={len(state['questions'])} "
                  f"created_kps={diff['created_kps']} "
                  f"created_mappings={diff['created_mappings']} "
                  f"updated_positions={diff['updated_positions']} "
                  f"duplicate_input_items={diff['duplicate_input_items']}")
            failures = _run_planned_gates(state, plan, diff, args)
            if failures:
                for f in failures:
                    logger.error("  ✗ %s", f)
                logger.error("dry-run: PLANNED GATES FAILED (%d)", len(failures))
                return 1
            logger.info("dry-run: PLANNED GATES PASS")
            return 0

        # ── 实写（单事务；门禁失败 → rollback + exit 1）──
        try:
            # _load_state 的 SELECT 已隐式开启只读事务；先回滚结束它，
            # 否则 async with db.begin() 报 "transaction is already begun"。
            await db.rollback()
            async with db.begin():
                # 1. 建主表（按 subject_id+normalized_name 幂等）
                for subject_id, display, norm, key in new_kps:
                    exists = await db.execute(
                        text(
                            "SELECT id FROM knowledge_points "
                            "WHERE subject_id=:s AND normalized_name=:n"
                        ),
                        {"s": subject_id, "n": norm},
                    )
                    row = exists.first()
                    if row:
                        # 并发/重复：用已存在 id
                        state["kp_by_key"][key] = (row[0], display)
                    else:
                        kp = KnowledgePoint(subject_id=subject_id, name=display, normalized_name=norm)
                        db.add(kp)
                        await db.flush()
                        state["kp_by_key"][key] = (kp.id, display)

                # 2. 建/更新映射
                for p in plan:
                    existing = state["map_by_q"].get(p["qid"], {})
                    for kp_id, position in p["kp_ids"]:
                        if kp_id < 0:
                            kp_id = state["kp_by_key"][(p["subject_id"], p["entries"][position][1])][0]
                        old_pos = existing.get(kp_id)
                        if old_pos is None:
                            db.add(QuestionKnowledgePoint(
                                question_id=p["qid"], knowledge_point_id=kp_id,
                                role="main", weight=1.0, source="backfill",
                                position=position,
                            ))
                        elif old_pos != position:
                            await db.execute(
                                text(
                                    "UPDATE question_knowledge_points SET position=:pos "
                                    "WHERE question_id=:q AND knowledge_point_id=:k"
                                ),
                                {"pos": position, "q": p["qid"], "k": kp_id},
                            )
                await db.flush()

                # 3. 门禁（对写后内存状态）
                failures = _run_planned_gates(state, plan, diff, args)
                if failures:
                    for f in failures:
                        logger.error("  ✗ %s", f)
                    logger.error("GATES FAILED (%d) — rollback", len(failures))
                    raise RuntimeError("backfill gate failure; rolling back")
        except Exception as exc:
            logger.error("backfill failed: %s", exc)
            return 1
        # begin() 正常退出 → commit

    print(f"[done] questions={len(state['questions'])} created_kps={diff['created_kps']} "
          f"created_mappings={diff['created_mappings']} updated_positions={diff['updated_positions']}")
    logger.info("backfill committed successfully")
    return 0


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

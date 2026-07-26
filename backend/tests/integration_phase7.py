"""阶段七：AI 辅助导题系统 集成测试

覆盖：
1. 健康检查 + 登录 → 获取 token
2. enrich：AI 标知识点/章节/难度（实调 + 降级两条路径）
3. complete：AI 补全缺失字段（answer 不直接落入 parsed_answer）
4. generate：AI 批量生成草稿（独立批次 AIGEN_*）
5. enrich-batch：批量补全
6. logs：调用审计可查
7. 审核流：AI 元数据中的 knowledge_points / difficulty 在 approve 时合并到 questions 表
8. 安全约束：AI 草稿绝不直接进入 questions 表

运行：
  cd backend
  python3 -m tests.integration_phase7
"""
import asyncio
import os
import sys
import uuid

# 强制使用临时数据库，避免污染开发库
_TEST_DB_PATH = f"./_test_phase7_{uuid.uuid4().hex[:6]}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ.setdefault("APP_ENV", "test")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.database import Base, async_session, engine  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models.ai_chat import AiChat  # noqa: E402,F401
from app.models.ai_generation_log import AiGenerationLog  # noqa: E402,F401
from app.models.answer_behavior import AnswerBehavior  # noqa: E402,F401
from app.models.practice_record import PracticeRecord  # noqa: E402,F401
from app.models.question import Question  # noqa: E402,F401
from app.models.question_import import QuestionImport  # noqa: E402,F401
from app.models.tag import Tag  # noqa: E402,F401

# 注册所有 model 到 metadata（顺序保持与 alembic env.py 一致）
from app.models.user import User  # noqa: E402,F401
from app.models.wrong_question import WrongQuestion  # noqa: E402,F401

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def _ok(name: str) -> None:
    PASSED.append(name)
    print(f"  ✓ {name}")


def _fail(name: str, msg: str) -> None:
    FAILED.append((name, msg))
    print(f"  ✗ {name}: {msg}")


def check(name: str, cond: bool, msg: str = "") -> bool:
    if cond:
        _ok(name)
        return True
    _fail(name, msg)
    return False


async def setup_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def teardown_db() -> None:
    await engine.dispose()
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)


async def seed_pending_imports(batch_id: str) -> list[int]:
    """直接写入 question_imports，模拟用户已经上传过 Excel/PDF。"""
    ids: list[int] = []
    async with async_session() as db:
        # 1) 学科+答案都已知（用于 enrich 测试）
        q1 = QuestionImport(
            batch_id=batch_id,
            source_type="excel",
            source_file="seed.xlsx",
            subject="math2",
            question_type="choice",
            raw_data={"stem": "若 f(x)=x^2 ，则 f'(1) = ?"},
            parsed_content={"text": "若 f(x)=x^2 ，则 f'(1) = ?"},
            parsed_options={"A": "1", "B": "2", "C": "x", "D": "2x"},
            parsed_answer="B",
            parsed_analysis="f'(x)=2x，代入 x=1 得 2。",
            status="pending",
        )
        # 2) 缺学科/答案/解析（用于 complete 测试）
        q2 = QuestionImport(
            batch_id=batch_id,
            source_type="pdf",
            source_file="seed.pdf",
            raw_data={"stem": "1 + 1 = ?"},
            parsed_content={"text": "1 + 1 = ?"},
            parsed_options={"A": "1", "B": "2", "C": "3", "D": "4"},
            status="pending",
        )
        # 3) 已审核（不允许 AI 操作）
        q3 = QuestionImport(
            batch_id=batch_id,
            source_type="excel",
            source_file="seed.xlsx",
            subject="math2",
            question_type="choice",
            raw_data={"stem": "已审核题"},
            parsed_content={"text": "已审核题"},
            parsed_answer="A",
            status="approved",
        )
        db.add_all([q1, q2, q3])
        await db.commit()
        await db.refresh(q1)
        await db.refresh(q2)
        await db.refresh(q3)
        ids = [q1.id, q2.id, q3.id]
    return ids


async def login(client: httpx.AsyncClient) -> str:
    res = await client.post("/api/v1/auth/login", json={"code": "phase7-test-code"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


# ───────────────────────────── 测试用例 ─────────────────────────────


async def case_health(client: httpx.AsyncClient) -> None:
    print("\n[1] 健康检查 + 登录")
    res = await client.get("/health")
    check("GET /health 200", res.status_code == 200,
          f"status={res.status_code}")
    res = await client.post("/api/v1/auth/login", json={"code": "phase7-x"})
    check("POST /auth/login 200", res.status_code == 200, res.text)
    body = res.json()
    check("login 返回 access_token", "access_token" in body, str(body))


async def case_enrich(client: httpx.AsyncClient, headers: dict, ids: list[int]) -> None:
    print("\n[2] enrich：AI 标知识点/章节/难度")
    qi_id_known, _, qi_id_approved = ids

    # 2.1 实调 AI（如 API 可用）
    res = await client.post(f"/api/v1/ai-import/enrich/{qi_id_known}", headers=headers)
    check("POST /enrich/{id} 200", res.status_code == 200, res.text)
    body = res.json()
    check("响应包含 ai_metadata", "ai_metadata" in body, str(body))
    check("响应包含 from_fallback", "from_fallback" in body, str(body))

    # 2.2 落库验证
    async with async_session() as db:
        qi = (await db.execute(
            select(QuestionImport).where(QuestionImport.id == qi_id_known)
        )).scalar_one()
        check("ai_generated=True", qi.ai_generated is True,
              f"ai_generated={qi.ai_generated}")
        check("ai_source='enrich'", qi.ai_source == "enrich",
              f"ai_source={qi.ai_source}")
        check("ai_metadata 已写入", isinstance(qi.ai_metadata, dict),
              f"ai_metadata={qi.ai_metadata}")
        check("ai_raw_response 已写入", bool(qi.ai_raw_response),
              "ai_raw_response 为空")
        # status 不应改变
        check("status 仍为 pending", qi.status == "pending",
              f"status={qi.status}")

    # 2.3 对已审核记录调用应被拒
    res = await client.post(f"/api/v1/ai-import/enrich/{qi_id_approved}", headers=headers)
    check("approved 记录 enrich 应 404", res.status_code == 404,
          f"status={res.status_code}, body={res.text}")

    # 2.4 不存在 ID
    res = await client.post("/api/v1/ai-import/enrich/999999", headers=headers)
    check("不存在 ID 应 404", res.status_code == 404,
          f"status={res.status_code}")


async def case_complete(client: httpx.AsyncClient, headers: dict, ids: list[int]) -> None:
    print("\n[3] complete：AI 补全缺失字段（answer 安全策略）")
    _, qi_id_missing, _ = ids

    # 拿到原始状态
    async with async_session() as db:
        qi_before = (await db.execute(
            select(QuestionImport).where(QuestionImport.id == qi_id_missing)
        )).scalar_one()
        original_answer = qi_before.parsed_answer

    res = await client.post(f"/api/v1/ai-import/complete/{qi_id_missing}", headers=headers)
    check("POST /complete/{id} 200", res.status_code == 200, res.text)
    body = res.json()
    check("响应包含 missing 字段", "missing" in body and isinstance(body["missing"], list),
          str(body))
    check("missing 包含 subject", "subject" in body["missing"], str(body["missing"]))
    check("missing 包含 answer", "answer" in body["missing"], str(body["missing"]))

    # 关键安全约束：parsed_answer 绝不应被 AI 自动覆盖
    async with async_session() as db:
        qi_after = (await db.execute(
            select(QuestionImport).where(QuestionImport.id == qi_id_missing)
        )).scalar_one()
        check("parsed_answer 未被 AI 自动写入", qi_after.parsed_answer == original_answer,
              f"before={original_answer!r} after={qi_after.parsed_answer!r}")
        meta = qi_after.ai_metadata or {}
        sugg = meta.get("complete_suggestion") or {}
        # 若 AI 给了答案建议，必须挂在 ai_metadata 上且置 ai_answer_flag
        if not body.get("from_fallback") and "answer" in sugg:
            check("AI 给出答案时 ai_answer_flag=True", qi_after.ai_answer_flag is True,
                  f"ai_answer_flag={qi_after.ai_answer_flag}")
            check("AI 答案落在 ai_metadata.complete_suggestion.answer",
                  bool(sugg.get("answer")), f"sugg={sugg}")
        # subject 在缺失情况下允许 AI 写入
        if not body.get("from_fallback") and sugg.get("subject"):
            check("缺失 subject 时 AI 可直接补到 qi.subject",
                  qi_after.subject == sugg["subject"],
                  f"qi.subject={qi_after.subject} sugg={sugg.get('subject')}")


async def case_generate(client: httpx.AsyncClient, headers: dict) -> str:
    print("\n[4] generate：AI 生成草稿题")
    payload = {
        "subject": "math2",
        "knowledge_points": ["求导公式"],
        "difficulty": 2,
        "count": 2,
        "question_type": "choice",
    }
    res = await client.post("/api/v1/ai-import/generate", json=payload, headers=headers)
    check("POST /generate 200", res.status_code == 200, res.text)
    body = res.json()
    batch_id = body.get("batch_id", "")
    check("返回 batch_id 形如 AIGEN_*", batch_id.startswith("AIGEN_"),
          f"batch_id={batch_id}")
    check("generated >= 0", body.get("generated", -1) >= 0, str(body))

    # 入库验证：草稿写到 question_imports.status=pending 且 source_type=ai_generated
    async with async_session() as db:
        rows = (await db.execute(
            select(QuestionImport).where(QuestionImport.batch_id == batch_id)
        )).scalars().all()
        if not body.get("from_fallback"):
            check("生成的草稿入暂存区", len(rows) > 0, "草稿数=0")
        for r in rows:
            check(f"草稿 #{r.id} source_type=ai_generated",
                  r.source_type == "ai_generated", f"source_type={r.source_type}")
            check(f"草稿 #{r.id} status=pending",
                  r.status == "pending", f"status={r.status}")
            check(f"草稿 #{r.id} ai_generated=True",
                  r.ai_generated is True, f"ai_generated={r.ai_generated}")
            check(f"草稿 #{r.id} 无 question_id（未入正式题库）",
                  r.question_id is None, f"question_id={r.question_id}")
        # 关键安全约束：generate 不应往 questions 表插入任何记录
        qcount = (await db.execute(
            select(Question).where(Question.import_batch_id == batch_id)
        )).scalars().all()
        check("questions 表内没有该批次的正式题",
              len(qcount) == 0, f"questions 中泄漏了 {len(qcount)} 道")

    # 非法 subject
    res = await client.post(
        "/api/v1/ai-import/generate",
        json={"subject": "physics", "knowledge_points": [], "count": 1},
        headers=headers,
    )
    check("非法 subject 应 400", res.status_code == 400,
          f"status={res.status_code}, body={res.text}")
    return batch_id


async def case_enrich_batch(client: httpx.AsyncClient, headers: dict, batch_id: str) -> None:
    print("\n[5] enrich-batch：批量补全")
    res = await client.post(f"/api/v1/ai-import/enrich-batch/{batch_id}", headers=headers)
    check("POST /enrich-batch/{batch_id} 200", res.status_code == 200, res.text)
    body = res.json()
    check("响应包含 processed/succeeded/fallback",
          {"processed", "succeeded", "fallback"} <= body.keys(),
          str(body))
    check("succeeded + fallback == processed",
          body["succeeded"] + body["fallback"] == body["processed"],
          str(body))


async def case_logs(client: httpx.AsyncClient, headers: dict) -> None:
    print("\n[6] logs：审计可查")
    res = await client.get("/api/v1/ai-import/logs?page=1&page_size=50", headers=headers)
    check("GET /logs 200", res.status_code == 200, res.text)
    body = res.json()
    items = body.get("items", [])
    check("logs 返回非空", len(items) > 0, "logs items 为空")
    actions = {it["action"] for it in items}
    check("logs 至少覆盖 enrich/complete/generate 中两种以上",
          len(actions & {"enrich", "complete", "generate"}) >= 2,
          f"actions={actions}")

    # 按 action 过滤
    res2 = await client.get("/api/v1/ai-import/logs?action=enrich", headers=headers)
    check("GET /logs?action=enrich 200", res2.status_code == 200, res2.text)
    items2 = res2.json().get("items", [])
    check("过滤后仅含 enrich",
          all(it["action"] == "enrich" for it in items2),
          str({it["action"] for it in items2}))


async def case_approve_merges_ai_metadata(
    client: httpx.AsyncClient, headers: dict, ids: list[int]
) -> None:
    print("\n[7] 审核流：approve 时合并 AI 元数据到 questions 表")
    qi_id_known = ids[0]

    # 取 enrich 后的 ai_metadata
    async with async_session() as db:
        qi = (await db.execute(
            select(QuestionImport).where(QuestionImport.id == qi_id_known)
        )).scalar_one()
        ai_kps = (qi.ai_metadata or {}).get("knowledge_points") or []
        ai_diff = (qi.ai_metadata or {}).get("difficulty")

    res = await client.put(
        f"/api/v1/import/questions/{qi_id_known}",
        json={"status": "approved"},
        headers=headers,
    )
    check("PUT /import/questions/{id} approved 200", res.status_code == 200, res.text)
    body = res.json()
    new_qid = body.get("question_id")
    check("approve 返回 question_id", isinstance(new_qid, int), str(body))

    async with async_session() as db:
        q = (await db.execute(
            select(Question).where(Question.id == new_qid)
        )).scalar_one()
        if ai_kps:
            check("ai_metadata.knowledge_points 合并到 questions.knowledge_points",
                  q.knowledge_points == ai_kps,
                  f"q.kps={q.knowledge_points} ai_kps={ai_kps}")
        if isinstance(ai_diff, int) and 1 <= ai_diff <= 5:
            check("ai_metadata.difficulty 合并到 questions.difficulty",
                  q.difficulty == ai_diff,
                  f"q.diff={q.difficulty} ai_diff={ai_diff}")

        qi = (await db.execute(
            select(QuestionImport).where(QuestionImport.id == qi_id_known)
        )).scalar_one()
        check("approve 后 status=approved", qi.status == "approved",
              f"status={qi.status}")
        check("AI 题审核盖 ai_reviewed_at 时间戳",
              qi.ai_reviewed_at is not None,
              f"ai_reviewed_at={qi.ai_reviewed_at}")


async def case_no_auth(client: httpx.AsyncClient) -> None:
    print("\n[8] 未登录访问应拒绝")
    res = await client.post("/api/v1/ai-import/enrich/1")
    check("无 token 访问应 401/403",
          res.status_code in (401, 403),
          f"status={res.status_code}")


async def case_fallback(client: httpx.AsyncClient, headers: dict) -> None:
    print("\n[9] AI 不可用时的降级路径")
    # 临时移除 API key，让 deepseek.is_available() 返回 False
    from app.ai.client import deepseek
    original_key = deepseek.api_key
    deepseek.api_key = ""
    try:
        # 准备一条新的 pending 用于降级测试
        async with async_session() as db:
            qi = QuestionImport(
                batch_id="FALLBACK_BATCH",
                source_type="excel",
                source_file="x.xlsx",
                subject="math2",
                question_type="choice",
                raw_data={"stem": "降级测试题"},
                parsed_content={"text": "降级测试题"},
                parsed_options={"A": "1", "B": "2"},
                parsed_answer="A",
                status="pending",
            )
            db.add(qi)
            await db.commit()
            await db.refresh(qi)
            qi_id = qi.id

        res = await client.post(f"/api/v1/ai-import/enrich/{qi_id}", headers=headers)
        check("enrich 在 API 不可用时仍返回 200",
              res.status_code == 200, res.text)
        body = res.json()
        check("from_fallback=True", body.get("from_fallback") is True, str(body))

        res = await client.post(
            "/api/v1/ai-import/generate",
            json={"subject": "math2", "knowledge_points": ["导数"],
                  "count": 1, "question_type": "choice"},
            headers=headers,
        )
        check("generate 在 API 不可用时仍返回 200",
              res.status_code == 200, res.text)
        body = res.json()
        check("generate from_fallback=True 且 generated=0",
              body.get("from_fallback") is True and body.get("generated") == 0,
              str(body))

        # 降级时应记审计日志
        async with async_session() as db:
            logs = (await db.execute(
                select(AiGenerationLog).where(AiGenerationLog.model == "fallback")
            )).scalars().all()
            check("降级也写入 ai_generation_logs",
                  len(logs) >= 2, f"fallback 日志数={len(logs)}")
            for lg in logs:
                check(f"降级日志 #{lg.id} success=0", lg.success == 0,
                      f"success={lg.success}")
    finally:
        deepseek.api_key = original_key


# ───────────────────────────── 主流程 ─────────────────────────────


async def main() -> int:
    print("=" * 60)
    print("阶段七：AI 辅助导题系统 集成测试")
    print(f"数据库：{_TEST_DB_PATH}")
    print("=" * 60)

    await setup_db()

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
        try:
            await case_health(client)
            token = await login(client)
            headers = {"Authorization": f"Bearer {token}"}

            batch_id = "SEED_PHASE7"
            ids = await seed_pending_imports(batch_id)
            await case_enrich(client, headers, ids)
            await case_complete(client, headers, ids)
            gen_batch = await case_generate(client, headers)
            await case_enrich_batch(client, headers, gen_batch)
            await case_logs(client, headers)
            await case_approve_merges_ai_metadata(client, headers, ids)
            await case_no_auth(client)
            await case_fallback(client, headers)
        except Exception as e:  # noqa: BLE001
            _fail("UNEXPECTED EXCEPTION", repr(e))
            import traceback
            traceback.print_exc()

    await teardown_db()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("\n失败明细：")
        for name, msg in FAILED:
            print(f"  ✗ {name}\n    {msg}")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

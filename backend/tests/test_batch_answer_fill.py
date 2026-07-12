"""Phase 1：快速补充答案（答案串补录）测试。

覆盖 20 个测试点。

运行：
  cd backend
  python3 -m tests.test_batch_answer_fill
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime

_TEST_DB_PATH = f"./_test_batch_answer_{uuid.uuid4().hex[:6]}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ.setdefault("APP_ENV", "test")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from app.core.database import Base, async_session, engine
# Register all models
from app.models.user import User  # noqa: E402,F401
from app.models.question import Question  # noqa: E402,F401
from app.models.question_import import QuestionImport  # noqa: E402,F401
from app.models.admin import AuditLog  # noqa: E402,F401 — pre-register table for create_all

from app.main import app as fastapi_app  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


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
    _fail(name, msg or "条件不满足")
    return False


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════

_BASE_URL = "http://test"


async def _setup_db():
    """初始化数据库和基础数据。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    db = async_session()
    try:
        # 创建管理员角色和用户
        from app.core.admin_security import hash_admin_password
        from app.models.admin import AdminUser, Role, Permission, RolePermission

        # 创建测试角色
        role = Role(name="test_admin", display_name="测试管理员", is_system=False)
        db.add(role)
        await db.flush()

        # 创建 import:read 和 import:write 权限
        perm_read = Permission(name="import:read", resource="import", action="read", category="import")
        perm_write = Permission(name="import:write", resource="import", action="write", category="import")
        db.add_all([perm_read, perm_write])
        await db.flush()

        # 角色权限绑定
        db.add(RolePermission(role_id=role.id, permission_id=perm_read.id))
        db.add(RolePermission(role_id=role.id, permission_id=perm_write.id))

        # 创建测试管理员
        admin = AdminUser(
            username="test_admin",
            password_hash=hash_admin_password("test123"),
            display_name="Test",
            is_active=True,
            role_id=role.id,
        )
        db.add(admin)
        await db.flush()

        # 创建受限管理员（只有 import:read 无 write）
        role_ro = Role(name="test_ro", display_name="只读管理员", is_system=False)
        db.add(role_ro)
        await db.flush()
        db.add(RolePermission(role_id=role_ro.id, permission_id=perm_read.id))

        admin_ro = AdminUser(
            username="test_ro",
            password_hash=hash_admin_password("test123"),
            display_name="ReadOnly",
            is_active=True,
            role_id=role_ro.id,
        )
        db.add(admin_ro)
        await db.flush()

        # 创建测试科目
        from app.models.admin import Subject
        subject = Subject(code="408", name="计算机", level=1, path="/1", sort_order=1)
        db.add(subject)
        await db.flush()

        # 创建测试题目（batch_id = "test_batch_1"，100 题）
        batch_id = "test_batch_1"
        question_id = 0
        for i in range(100):
            qtype = "single_choice"
            answer = None
            # 第 2 题（index=1）设置已有答案 "D"
            if i == 1:
                answer = "D"
            # 第 50 题设为多选题
            if i == 49:
                qtype = "multi_choice"
            # 第 75 题设为判断题
            if i == 74:
                qtype = "true_false"
            # 第 85 题设为不支持的题型
            if i == 84:
                qtype = "fill_blank"

            question_id += 1
            qi = QuestionImport(
                batch_id=batch_id,
                source_type="image",
                source_file="test.png",
                question_type=qtype,
                source_order_index=i,
                source_question_no=str(i + 1),
                parsed_content={"stem": f"这是第{i+1}题，用于测试快速补充答案功能。"},
                parsed_answer=answer,
                parsed_options={"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"},
                status="pending",
                answer_status="manual_filled" if answer else None,
                answer_source="manual" if answer else None,
                raw_data={"raw_text": f"{i+1}. 这是第{i+1}题……"},
                raw_text_preview=f"{i+1}. 这是第{i+1}题……",
            )
            db.add(qi)

        await db.commit()
    finally:
        await db.close()


def _login_url() -> str:
    return f"{_BASE_URL}/api/admin/v1/auth/login"


def _preview_url(batch_id: str) -> str:
    return f"{_BASE_URL}/api/admin/v1/imports/{batch_id}/answers/preview"


def _apply_url(batch_id: str) -> str:
    return f"{_BASE_URL}/api/admin/v1/imports/{batch_id}/answers/apply"


async def _login(client: httpx.AsyncClient, username: str = "test_admin") -> str:
    resp = await client.post(_login_url(), json={"username": username, "password": "test123"})
    data = resp.json()
    return data.get("access_token", "")


async def _auth_headers(client: httpx.AsyncClient, username: str = "test_admin") -> dict:
    token = await _login(client, username)
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════
# 主测试
# ══════════════════════════════════════════════════════════


async def run_tests():
    await _setup_db()

    async with httpx.AsyncClient(transport=ASGITransport(app=fastapi_app), base_url=_BASE_URL) as client:
        headers = await _auth_headers(client)
        ro_headers = await _auth_headers(client, "test_ro")

        print("\n========== Phase 1：快速补充答案 测试 ==========\n")

        # ─── 1. abcda 转换为 ABCDA ───
        print("\n--- 1. abcda 转换 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "abcda", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("1.1 返回 200", resp.status_code == 200, str(resp.status_code))
        check("1.2 summary 有值", "summary" in data)
        check("1.3 parsed_answer_count=5", data["summary"]["parsed_answer_count"] == 5)
        # 前 5 题都应该标为将写入，且答案标准化
        update_items = [it for it in data["items"] if it["will_update"]]
        check("1.4 5 个将写入项", len(update_items) == 4)  # 第 2 题已有答案跳过，所以只有 4 个写入
        if update_items:
            check("1.5 第一题答案=A", update_items[0]["normalized_answer"] == "A")

        # ─── 2. 混合大小写 ───
        print("\n--- 2. 混合大小写 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "AbCdA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("2.1 返回 200", resp.status_code == 200)
        check("2.2 parsed=5", data["summary"]["parsed_answer_count"] == 5)
        update_items = [it for it in data["items"] if it["will_update"]]
        if len(update_items) >= 3:
            check("2.3 第1题[A]", update_items[0]["normalized_answer"] == "A")
            check("2.4 第3题[C]", update_items[1]["normalized_answer"] == "C")  # 第2题跳过
            check("2.5 第4题[D]", update_items[2]["normalized_answer"] == "D")

        # ─── 3. 空格/逗号分隔 ───
        print("\n--- 3. 分隔符解析 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "A B, C, D\nA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("3.1 返回 200", resp.status_code == 200)
        check("3.2 parsed=5", data["summary"]["parsed_answer_count"] == 5)

        # ─── 4. 5 个答案对应 100 题中的前 5 题 ───
        print("\n--- 4. 前 5 题处理 ---")
        check("4.1 batch_total=100", data["summary"]["batch_total"] == 100)
        check("4.2 target=5", data["summary"]["target_question_count"] == 5)
        check("4.3 remaining=95", data["summary"]["remaining_question_count"] == 95)

        # ─── 5. 已有答案跳过但占用位置 ───
        print("\n--- 5. 已有答案跳过 ---")
        # 第 2 题已有答案 D，输入 A,B,C,D,A
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "ABCDA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("5.1 skipped_existing=1", data["summary"]["skipped_existing_count"] == 1)
        # 第 2 题的 items 应该标记为 skip_existing，且在位置 1
        items = data["items"]
        check("5.2 第2题跳过", items[1]["status"] == "skip_existing")
        check("5.3 第2题保留原答案", items[1]["original_answer"] == "D")
        # 第3题仍然在第2个 will_update 项
        update_items = [it for it in items if it["will_update"]]
        check("5.4 共4个写入项", len(update_items) == 4)
        check("5.5 第2个写入项是第3题", update_items[1]["import_id"] == items[2]["import_id"])

        # ─── 6. 答案数超过题目数时拒绝 ───
        print("\n--- 6. 超过题目数拒绝 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "A" * 101, "allow_partial_prefix": True},
            headers=headers,
        )
        check("6.1 返回 422", resp.status_code == 422)

        # ─── 7. source_order_index 顺序正确 ───
        print("\n--- 7. source_order_index 顺序 ---")
        items = data["items"] if resp.status_code == 200 else []
        # 在第 4 个测试中 data 是有效的
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "ABCDA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        items = data["items"]
        # source_order_index 应该是 0, 1, 2, 3, 4
        indices = [it["source_order_index"] for it in items[:5]]
        check("7.1 前5题顺序索引", indices == [0, 1, 2, 3, 4], str(indices))

        # ─── 8. source_order_index 重复应失败 ───
        print("\n--- 8. order 重复检测 ---")
        db = async_session()
        try:
            qi_dup = QuestionImport(
                batch_id="test_dup_batch",
                source_type="image",
                source_file="test.png",
                question_type="single_choice",
                source_order_index=1,
                source_question_no="2b",
                parsed_content={"stem": "重复顺序索引测试题"},
                parsed_options={"A": "AA", "B": "BB", "C": "CC", "D": "DD"},
                status="pending",
                raw_data={"raw_text": "2b. 重复顺序索引"},
            )
            db.add(qi_dup)
            qi_first = QuestionImport(
                batch_id="test_dup_batch",
                source_type="image",
                source_file="test.png",
                question_type="single_choice",
                source_order_index=1,
                source_question_no="2a",
                parsed_content={"stem": "重复顺序索引测试题A"},
                parsed_options={"A": "AA", "B": "BB", "C": "CC", "D": "DD"},
                status="pending",
                raw_data={"raw_text": "2a. 重复顺序索引A"},
            )
            db.add(qi_first)
            qi0 = QuestionImport(
                batch_id="test_dup_batch",
                source_type="image",
                source_file="test.png",
                question_type="single_choice",
                source_order_index=0,
                source_question_no="1",
                parsed_content={"stem": "第一题"},
                parsed_options={"A": "AA", "B": "BB", "C": "CC", "D": "DD"},
                status="pending",
                raw_data={"raw_text": "1. 第一题"},
            )
            db.add(qi0)
            await db.commit()
        finally:
            await db.close()

        resp = await client.post(
            _preview_url("test_dup_batch"),
            json={"raw_text": "ABC", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("8.1 重复索引时返回 422", resp.status_code == 422,
              f"expected 422 got {resp.status_code}")
        # error_code 应为 ORDER_INDEX_DUPLICATED
        detail = data if isinstance(data, dict) else {}
        check("8.2 错误码 ORDER_INDEX_DUPLICATED",
              isinstance(detail, dict) and detail.get("detail", {}).get("error_code") == "ORDER_INDEX_DUPLICATED",
              f"error_code={detail.get('detail', {}).get('error_code')}, body={str(detail)[:200]}")

        # ─── 9. source_order_index 为空应失败 ───
        print("\n--- 9. order 为空检测 ---")
        db = async_session()
        try:
            qi_null = QuestionImport(
                batch_id="test_null_batch",
                source_type="image",
                source_file="test.png",
                question_type="single_choice",
                source_order_index=None,
                source_question_no="1",
                parsed_content={"stem": "空顺序索引测试"},
                parsed_options={"A": "AA", "B": "BB", "C": "CC", "D": "DD"},
                status="pending",
                raw_data={"raw_text": "1. 空顺序索引"},
            )
            db.add(qi_null)
            await db.commit()
        finally:
            await db.close()

        resp = await client.post(
            _preview_url("test_null_batch"),
            json={"raw_text": "A", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("9.1 空顺序索引时 422", resp.status_code == 422,
              f"expected 422 got {resp.status_code}")
        detail = data if isinstance(data, dict) else {}
        check("9.2 错误码 ORDER_INDEX_MISSING",
              detail.get("detail", {}).get("error_code") == "ORDER_INDEX_MISSING",
              str(detail.get("detail", {}).get("error_code")))

        # ─── 10. 非法答案 E 被拒绝（当题目无 E 选项） ───
        print("\n--- 10. 非法答案 E ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "E", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("10.1 返回 200", resp.status_code == 200)
        invalid_items = [it for it in data.get("items", []) if it["status"] == "invalid_answer"]
        check("10.2 无效答案标记", len(invalid_items) >= 1)

        # ─── 11. 多选答案 AC 标准化 ───
        print("\n--- 11. 多选 AC 标准化 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "AC", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        if data.get("items") and len(data["items"]) > 0:
            # 第 50 题是多选题（index=49），但这里只处理前 1 题（AC 是 1 个多选答案）
            # AC 被解析为第 1 题（单选题），会被标记非法
            pass

        # 直接测试第 50 题（多选题）
        # 先用 raw_text 覆盖前 50 题，但正确答案是 "AC"
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "A\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nAC", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        items = data.get("items", [])
        if len(items) >= 50:
            mc_item = items[49]
            check("11.1 第50题是多选题", mc_item["question_type"] == "multi_choice")
            if mc_item["will_update"]:
                check("11.2 多选答案=AC", mc_item["normalized_answer"] == "AC")

        # ─── 12. 多选答案 CA 标准化为 AC ───
        print("\n--- 12. CA → AC 标准化 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "A\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nCA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        items = data.get("items", [])
        if len(items) >= 50:
            mc_item = items[49]
            if mc_item["will_update"]:
                check("12.1 CA→AC", mc_item["normalized_answer"] == "AC")

        # ─── 13. 判断题格式转换 ───
        print("\n--- 13. 判断题格式 ---")
        from app.services.batch_answer_service import normalize_single_answer
        norm_t, err_t = normalize_single_answer("T", "true_false")
        check("13.1 T→T", norm_t == "T" and not err_t)
        norm_true, err_true = normalize_single_answer("TRUE", "true_false")
        check("13.2 TRUE→T", norm_true == "T")
        norm_f, err_f = normalize_single_answer("F", "true_false")
        check("13.3 F→F", norm_f == "F")
        norm_dui, err_dui = normalize_single_answer("对", "true_false")
        check("13.4 对→T", norm_dui == "T")
        norm_cuo, err_cuo = normalize_single_answer("错误", "true_false")
        check("13.5 错误→F", norm_cuo == "F")
        norm_sqrt, err_sqrt = normalize_single_answer("√", "true_false")
        check("13.6 √→T", norm_sqrt == "T")

        # ─── 14. 不支持题型跳过 ───
        print("\n--- 14. 不支持题型 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "A\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA\nA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        items = data.get("items", [])
        if len(items) >= 85:
            fill_item = items[84]
            check("14.1 第85题填空", fill_item["question_type"] == "fill_blank")
            check("14.2 不支持标记", fill_item["status"] == "unsupported_type")

        # ─── 15. 不能跨 batch_id 更新 ───
        print("\n--- 15. 跨批次检查 ---")
        resp = await client.post(
            _preview_url("nonexistent_batch"),
            json={"raw_text": "A", "allow_partial_prefix": True},
            headers=headers,
        )
        check("15.1 不存在批次 422", resp.status_code == 422)

        # ─── 16. preview 后原答案变化时 apply 拒绝 ───
        print("\n--- 16. 版本变化拒绝 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "BCDA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        token = data.get("preview_token", "")
        if token:
            # 修改一个题目的答案来模拟版本变化
            db = async_session()
            try:
                q = (await db.execute(
                    select(QuestionImport).where(QuestionImport.batch_id == "test_batch_1").order_by(QuestionImport.id).limit(1)
                )).scalar_one_or_none()
                if q:
                    q.parsed_answer = "X"
                    await db.commit()
            finally:
                await db.close()

            resp = await client.post(
                _apply_url("test_batch_1"),
                json={"preview_token": token},
                headers=headers,
            )
            check("16.1 版本变化 409", resp.status_code == 409)
            if resp.status_code == 409:
                detail = resp.json()
                check("16.2 错误码 PREVIEW_STALE",
                      detail.get("detail", {}).get("error_code") == "PREVIEW_STALE",
                      str(detail.get("detail", {}).get("error_code")))

        # ─── 17. 无权限管理员返回 403 ───
        print("\n--- 17. 无权限 403 ---")
        resp = await client.post(
            _preview_url("test_batch_1"),
            json={"raw_text": "A", "allow_partial_prefix": True},
            headers=ro_headers,
        )
        check("17.1 preview 无权限 403", resp.status_code == 403)
        resp2 = await client.post(
            _apply_url("test_batch_1"),
            json={"preview_token": "fake"},
            headers=ro_headers,
        )
        check("17.2 apply 无权限 403", resp2.status_code == 403)

        # ─── 18. 事务回滚 ───
        # （通过服务层验证，重复 source_order_index 在 apply 时检查版本）
        print("\n--- 18. 事务回滚 ---")
        db = async_session()
        try:
            qi_rollback = QuestionImport(
                batch_id="test_rollback_batch",
                source_type="image",
                source_file="test.png",
                question_type="single_choice",
                source_order_index=0,
                source_question_no="1",
                parsed_content={"stem": "回滚测试"},
                parsed_options={"A": "AA", "B": "BB", "C": "CC", "D": "DD"},
                status="pending",
                raw_data={"raw_text": "1. 回滚测试"},
            )
            db.add(qi_rollback)
            await db.commit()
        finally:
            await db.close()

        resp = await client.post(
            _preview_url("test_rollback_batch"),
            json={"raw_text": "A", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        token = data.get("preview_token", "")
        check("18.1 preview 成功", bool(token))

        if token:
            resp = await client.post(
                _apply_url("test_rollback_batch"),
                json={"preview_token": token},
                headers=headers,
            )
            check("18.2 apply 成功", resp.status_code in (200, 201))
            if resp.status_code in (200, 201):
                result = resp.json()
                check("18.3 updated_count=1", result.get("updated_count") == 1)
                check("18.4 有 operation_id", bool(result.get("operation_id")),
                      f"operation_id={result.get('operation_id')}")
                check("18.5 有 batch_stats", bool(result.get("batch_stats")),
                      str(result.get("batch_stats", {})))
                # 用同一 operation_id 重复提交应幂等
                opid = result.get("operation_id", "")
                if opid:
                    resp2 = await client.post(
                        _apply_url("test_rollback_batch"),
                        json={"preview_token": token, "operation_id": opid},
                        headers=headers,
                    )
                    check("18.6 operation_id 幂等返回 200", resp2.status_code in (200, 201),
                          f"expected 200 got {resp2.status_code}")
                    if resp2.status_code in (200, 201):
                        result2 = resp2.json()
                        check("18.7 幂等 updated_count 相同",
                              result2.get("updated_count") == result.get("updated_count"),
                              f"{result2.get('updated_count')} != {result.get('updated_count')}")

                        # 校验无重复审计日志
                        from app.models.admin import AuditLog
                        db2 = async_session()
                        try:
                            logs = (await db2.execute(
                                select(AuditLog).where(AuditLog.action == "import.batch_answer_fill")
                                .order_by(AuditLog.id.desc()).limit(10)
                            )).scalars().all()
                            opid_logs = [l for l in logs if (l.detail or {}).get("operation_id") == opid]
                            check("18.8 仅 1 条审计日志", len(opid_logs) == 1,
                                  f"found {len(opid_logs)} logs for opid {opid}")
                        finally:
                            await db2.close()

        # ─── 19. 审计日志记录 ───
        print("\n--- 19. 审计日志 ---")
        from app.models.admin import AuditLog
        db = async_session()
        try:
            logs = (await db.execute(
                select(AuditLog).where(AuditLog.action == "import.batch_answer_fill").order_by(AuditLog.id.desc()).limit(5)
            )).scalars().all()
            check("19.1 有审计日志", len(logs) > 0)
            if logs:
                log = logs[0]
                detail = log.detail or {}
                check("19.2 含操作数量", "written_count" in detail)
                check("19.3 含 operation_id", bool(detail.get("operation_id")),
                      f"operation_id not in detail: {detail}")
                check("19.4 不含题干", "stem" not in str(detail.get("detail", {})))
        finally:
            await db.close()

        # ─── 20. 重复 preview_token 不得重复更新 ───
        print("\n--- 20. 幂等性（token 防重放）---")
        if token:
            resp = await client.post(
                _apply_url("test_rollback_batch"),
                json={"preview_token": token},
                headers=headers,
            )
            check("20.1 重复提交幂等返回 200", resp.status_code == 200,
                  f"expected 200 got {resp.status_code} (operation_id cached)")

        # ─── 21. 批次不可编辑检测 ───
        print("\n--- 21. 批次不可编辑检测 ---")
        db = async_session()
        try:
            qi_approved = QuestionImport(
                batch_id="test_approved_batch",
                source_type="image",
                source_file="approved.png",
                question_type="single_choice",
                source_order_index=0,
                source_question_no="1",
                parsed_content={"stem": "已审批题"},
                parsed_options={"A": "AA", "B": "BB", "C": "CC", "D": "DD"},
                status="approved",  # 已审批，不可编辑
                raw_data={"raw_text": "1. 已审批题"},
            )
            db.add(qi_approved)
            await db.commit()
        finally:
            await db.close()

        resp = await client.post(
            _preview_url("test_approved_batch"),
            json={"raw_text": "A", "allow_partial_prefix": True},
            headers=headers,
        )
        check("21.1 已审批批次 preview 422", resp.status_code == 422)
        if resp.status_code == 422:
            detail = resp.json()
            check("21.2 错误码 BATCH_NOT_EDITABLE",
                  detail.get("detail", {}).get("error_code") == "BATCH_NOT_EDITABLE",
                  str(detail.get("detail", {}).get("error_code")))

        # ─── 22. writable_count=0 禁止 apply ───
        print("\n--- 22. writable_count=0 禁止 apply ---")
        db = async_session()
        try:
            qi_full = QuestionImport(
                batch_id="test_full_batch",
                source_type="image",
                source_file="full.png",
                question_type="single_choice",
                source_order_index=0,
                source_question_no="1",
                parsed_content={"stem": "已有答案题"},
                parsed_options={"A": "AA", "B": "BB", "C": "CC", "D": "DD"},
                parsed_answer="A",  # 已有答案
                answer_status="manual_filled",
                status="pending",
                raw_data={"raw_text": "1. 已有答案题"},
            )
            db.add(qi_full)
            await db.commit()
        finally:
            await db.close()

        # preview 应该显示 writable_count=0
        resp = await client.post(
            _preview_url("test_full_batch"),
            json={"raw_text": "B", "allow_partial_prefix": True},
            headers=headers,
        )
        check("22.1 preview 成功", resp.status_code == 200)
        if resp.status_code == 200:
            data = resp.json()
            check("22.2 writable_count=0", data["summary"]["writable_count"] == 0)
            token_zero = data.get("preview_token", "")
            opid_zero = data.get("operation_id", "")
            if token_zero:
                resp = await client.post(
                    _apply_url("test_full_batch"),
                    json={"preview_token": token_zero, "operation_id": opid_zero},
                    headers=headers,
                )
                check("22.3 writable_count=0 时 apply 422", resp.status_code == 422)
                if resp.status_code == 422:
                    detail = resp.json()
                    check("22.4 错误码 NO_WRITABLE_ITEMS",
                          detail.get("detail", {}).get("error_code") == "NO_WRITABLE_ITEMS",
                          str(detail.get("detail", {}).get("error_code")))

        # ─── 完整写入流程测试 ───
        print("\n--- 完整流程：preview → apply ---")
        # 创建一个干净的批次用于完整流程测试
        db = async_session()
        try:
            for i in range(5):
                qi = QuestionImport(
                    batch_id="test_flow_batch",
                    source_type="image",
                    source_file="flow.png",
                    question_type="single_choice",
                    source_order_index=i,
                    source_question_no=str(i + 1),
                    parsed_content={"stem": f"流程测试第{i+1}题"},
                    parsed_options={"A": "A", "B": "B", "C": "C", "D": "D"},
                    status="pending",
                    raw_data={"raw_text": f"{i+1}. 流程测试第{i+1}题"},
                )
                db.add(qi)
            await db.commit()
        finally:
            await db.close()

        # preview
        resp = await client.post(
            _preview_url("test_flow_batch"),
            json={"raw_text": "ABCDA", "allow_partial_prefix": True},
            headers=headers,
        )
        data = resp.json()
        check("flow.1 preview 成功", resp.status_code == 200)
        token = data.get("preview_token", "")
        check("flow.2 有 token", bool(token))
        check("flow.2b 有 operation_id", bool(data.get("operation_id")),
              f"operation_id={data.get('operation_id')}")
        check("flow.3 5 will_update", data["summary"]["writable_count"] == 5)
        check("flow.4 skipped=0", data["summary"]["skipped_existing_count"] == 0)

        if token:
            operation_id = data.get("operation_id", "")
            # apply
            resp = await client.post(
                _apply_url("test_flow_batch"),
                json={"preview_token": token, "operation_id": operation_id},
                headers=headers,
            )
            check("flow.5 apply 成功", resp.status_code in (200, 201))
            if resp.status_code in (200, 201):
                result = resp.json()
                check("flow.6 写入 5 题", result.get("updated_count") == 5)
                check("flow.7 返回 operation_id", result.get("operation_id") == operation_id)
                stats = result.get("batch_stats", {})
                check("flow.8 batch_stats 含 total_count", "total_count" in stats,
                      str(stats))
                check("flow.9 batch_stats 含 pending_count", "pending_count" in stats)
                check("flow.10 batch_stats 含 manual_filled_count",
                      stats.get("manual_filled_count", 0) >= 5,
                      f"manual_filled_count={stats.get('manual_filled_count')}")

    # ─── 清理临时数据库 ───
    await engine.dispose()
    if os.path.exists(_TEST_DB_PATH):
        os.unlink(_TEST_DB_PATH)

    # ─── 结果汇总 ───
    print(f"\n{'='*50}")
    print(f"通过: {len(PASSED)}")
    print(f"失败: {len(FAILED)}")
    if FAILED:
        for name, msg in FAILED:
            print(f"  ✗ {name}: {msg}")

    return len(FAILED)


if __name__ == "__main__":
    exit_code = asyncio.run(run_tests())
    sys.exit(exit_code)

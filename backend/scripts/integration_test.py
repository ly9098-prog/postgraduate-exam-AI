"""
集成测试（WeChat 登录版）：覆盖所有 15 个 API。
用法: python3 scripts/integration_test.py
"""

import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0


def req(method, path, token=None, body=None, expect=None):
    global PASS, FAIL
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(body).encode() if body else None
    req_obj = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req_obj, timeout=10)
        status = resp.status
        raw = resp.read().decode()
        result = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"raw": raw}
    except Exception as e:
        status = 0
        result = {"error": str(e)}

    ok = True
    if expect is not None and status != expect:
        ok = False
    if expect is None and status >= 500:
        ok = False

    label = f"{method} {path}"
    if ok:
        PASS += 1
        print(f"  ✅ {label} → {status}")
    else:
        FAIL += 1
        msg = json.dumps(result, ensure_ascii=False)[:120]
        print(f"  ❌ {label} → {status} (expected {expect}) | {msg}")

    return status, result


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ──────────────────────────────────────────
# Phase 1: 用户系统（微信登录）
# ──────────────────────────────────────────
section("阶段 1：用户系统（微信登录）")

# 1.1 微信 code 登录（开发模式自动创建用户）
status, data = req("POST", "/api/v1/auth/login", body={
    "code": "test_integration_code_001",
}, expect=200)
token = data.get("access_token", "")
assert token, "❌ 登录未返回 token"
user = data.get("user", {})
assert user.get("id"), "❌ 登录未返回用户信息"
print(f"     → user_id={user['id']}, token={token[:20]}...")

# 1.2 同一 code 再次登录（应返回同一用户）
status, data2 = req("POST", "/api/v1/auth/login", body={
    "code": "test_integration_code_001",
}, expect=200)
assert data2["user"]["id"] == user["id"], "❌ 同一 code 应返回同一用户"

# 1.3 不同 code 登录（应创建新用户）
status, data3 = req("POST", "/api/v1/auth/login", body={
    "code": "another_user_code",
}, expect=200)
assert data3["user"]["id"] != user["id"], "❌ 不同 code 应创建不同用户"

# 1.4 获取个人信息
req("GET", "/api/v1/users/me", token=token, expect=200)

# 1.5 无 token 访问
req("GET", "/api/v1/users/me")

# 1.6 后续测试用第一个用户
TOKEN = token


# ──────────────────────────────────────────
# Phase 2: 题库系统
# ──────────────────────────────────────────
section("阶段 2：题库系统")

status, q1 = req("POST", "/api/v1/questions", token=TOKEN, body={
    "subject": "math2",
    "question_type": "choice",
    "content": {"text": "极限 $\\lim_{x \\to 0} \\frac{\\sin x}{x} = ?$"},
    "options": {"A": "0", "B": "1", "C": "$\\infty$", "D": "不存在"},
    "answer": "B",
    "knowledge_points": ["极限", "重要极限"],
    "difficulty": 1,
}, expect=200)
q1_id = q1.get("id")

status, q2 = req("POST", "/api/v1/questions", token=TOKEN, body={
    "subject": "math2",
    "question_type": "choice",
    "content": {"text": "函数 $f(x)=x^2$ 的导数是？"},
    "options": {"A": "$2x$", "B": "$x$", "C": "$2$", "D": "$x^2$"},
    "answer": "A",
    "knowledge_points": ["导数"],
    "difficulty": 1,
}, expect=200)
q2_id = q2.get("id")

status, q3 = req("POST", "/api/v1/questions", token=TOKEN, body={
    "subject": "exam408",
    "question_type": "choice",
    "content": {"text": "TCP 工作在哪一层？"},
    "options": {"A": "网络层", "B": "传输层", "C": "应用层", "D": "链路层"},
    "answer": "B",
    "knowledge_points": ["TCP", "传输层"],
    "difficulty": 2,
}, expect=200)
q3_id = q3.get("id")

# 列表
status, data = req("GET", "/api/v1/questions?page=1&page_size=10", token=TOKEN, expect=200)
assert len(data.get("items", [])) == 3
req("GET", "/api/v1/questions?subject=exam408", token=TOKEN, expect=200)
req("GET", "/api/v1/questions/random", token=TOKEN, expect=200)
req("GET", f"/api/v1/questions/random?subject=math2&exclude_ids={q1_id},{q2_id}", token=TOKEN, expect=404)
req("GET", f"/api/v1/questions/{q1_id}", token=TOKEN, expect=200)
req("GET", "/api/v1/questions/99999", token=TOKEN, expect=404)


# ──────────────────────────────────────────
# Phase 3: 做题记录
# ──────────────────────────────────────────
section("阶段 3：做题记录")

status, data = req("POST", "/api/v1/practice/submit", token=TOKEN, body={
    "subject": "math2",
    "answers": [
        {"question_id": q1_id, "answer": "B"},
        {"question_id": q2_id, "answer": "C"},
    ],
    "duration_sec": 30,
}, expect=200)
assert data["correct_count"] == 1
assert data["wrong_count"] == 1
record1_id = data["record_id"]

req("POST", "/api/v1/practice/submit", token=TOKEN, body={
    "subject": "exam408",
    "answers": [{"question_id": q3_id, "answer": "A"}],
    "duration_sec": 15,
}, expect=200)

req("GET", "/api/v1/practice/records", token=TOKEN, expect=200)
req("GET", f"/api/v1/practice/records/{record1_id}", token=TOKEN, expect=200)
req("GET", "/api/v1/practice/records/99999", token=TOKEN, expect=404)
req("POST", "/api/v1/practice/submit", token=TOKEN, body={
    "subject": "math2",
    "answers": [{"question_id": 99999, "answer": "A"}],
}, expect=400)


# ──────────────────────────────────────────
# Phase 4: 错题本
# ──────────────────────────────────────────
section("阶段 4：错题本")

status, data = req("GET", "/api/v1/wrong-questions", token=TOKEN, expect=200)
assert data["total"] == 2

req("GET", "/api/v1/wrong-questions/stats", token=TOKEN, expect=200)

# 重复错
req("POST", "/api/v1/practice/submit", token=TOKEN, body={
    "subject": "math2",
    "answers": [{"question_id": q2_id, "answer": "D"}],
    "duration_sec": 10,
}, expect=200)

status, data = req("GET", "/api/v1/wrong-questions", token=TOKEN, expect=200)
q2_wrong = [w for w in data["items"] if w["question_id"] == q2_id][0]
assert q2_wrong["review_count"] >= 2
wrong_id = q2_wrong["id"]

# 标记已掌握
req("PUT", f"/api/v1/wrong-questions/{wrong_id}", token=TOKEN, body={
    "mastered": True,
}, expect=200)

req("GET", "/api/v1/wrong-questions?mastered=false", token=TOKEN, expect=200)
req("PUT", "/api/v1/wrong-questions/99999", token=TOKEN, body={"mastered": True}, expect=404)


# ──────────────────────────────────────────
# Phase 5: AI 模块
# ──────────────────────────────────────────
section("阶段 5：AI 解析模块")

print("  ⏳ 调用 DeepSeek API...")
start = time.time()
status, data = req("POST", "/api/v1/ai/error-analysis", token=TOKEN, body={
    "wrong_question_id": wrong_id,
}, expect=200)
elapsed = time.time() - start
print(f"     → {elapsed:.1f}s, tokens={data.get('tokens_used', 0)}")
assert data["from_fallback"] == False

# 缓存
start = time.time()
req("POST", "/api/v1/ai/error-analysis", token=TOKEN, body={
    "wrong_question_id": wrong_id,
}, expect=200)
print(f"     → 缓存命中，耗时 {time.time()-start:.3f}s")

# 学习建议
print("  ⏳ 获取学习建议...")
req("POST", "/api/v1/ai/study-advice", token=TOKEN, body={"subject": "math2"}, expect=200)

# 不存在错题
req("POST", "/api/v1/ai/error-analysis", token=TOKEN, body={
    "wrong_question_id": 99999,
}, expect=404)


# ──────────────────────────────────────────
# 结果
# ──────────────────────────────────────────
section("测试结果汇总")
total = PASS + FAIL
print(f"  总计: {total} 项")
print(f"  ✅ 通过: {PASS}")
print(f"  ❌ 失败: {FAIL}")
print(f"  通过率: {PASS/total*100:.1f}%" if total else "  无测试")
print()

if FAIL > 0:
    sys.exit(1)
else:
    print("  🎉 所有集成测试通过！")

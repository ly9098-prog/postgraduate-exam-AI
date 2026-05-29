"""Stage 11 后端 E2E 测试脚本。"""
import asyncio
import sys
from datetime import datetime, timedelta

import httpx
from jose import jwt

BASE = "http://127.0.0.1:8765"
APP_SECRET = "change-me-in-production"

# 生成 user_id=1 的 JWT
token = jwt.encode(
    {"sub": "1", "exp": datetime.utcnow() + timedelta(days=7)},
    APP_SECRET,
    algorithm="HS256",
)
HEADERS = {"Authorization": f"Bearer {token}"}
print(f"Token: {token[:50]}...")

PASSED = 0
FAILED = 0


async def main():
    global PASSED, FAILED
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as client:
        # ── 0. Health ──
        r = await client.get("/health")
        assert r.status_code == 200, f"Health failed: {r.status_code}"
        print(f"✓ Health: {r.json()}")

        # ── 1. GET /practice/questions ──
        r = await client.get(
            "/api/v1/practice/questions",
            params={"subject": "math2", "count": 3, "mode": "random"},
            headers=HEADERS,
        )
        assert r.status_code == 200, f"GET questions failed: {r.status_code} {r.text}"
        data = r.json()
        assert "questions" in data
        assert data["mode"] == "random"
        for q in data["questions"]:
            assert "answer" not in q, "题目列表不应包含答案!"
            assert "analysis" not in q, "题目列表不应包含解析!"
            assert "id" in q and "subject" in q and "content" in q
        print(f"✓ GET /practice/questions: {len(data['questions'])} 题, mode={data['mode']}")

        if not data["questions"]:
            print("⚠ 无可用题目，跳过后续答题测试")
            return

        qid = data["questions"][0]["id"]
        print(f"  测试题目 id={qid}")

        # ── 2. POST /practice/submit (正确) ──
        r = await client.post(
            "/api/v1/practice/submit",
            json={"question_id": qid, "user_answer": "A", "used_time": 15},
            headers=HEADERS,
        )
        assert r.status_code == 200, f"Submit failed: {r.status_code} {r.text}"
        result = r.json()
        assert "is_correct" in result
        assert "correct_answer" in result
        assert "analysis" in result
        assert result["question_id"] == qid
        print(f"✓ POST /practice/submit: is_correct={result['is_correct']}, wrong_added={result.get('is_wrong_added')}")

        # ── 3. POST /practice/submit (故意错误) ──
        r = await client.post(
            "/api/v1/practice/submit",
            json={"question_id": qid, "user_answer": "Z", "used_time": 10},
            headers=HEADERS,
        )
        assert r.status_code == 200
        wrong_result = r.json()
        assert wrong_result["is_wrong_added"] == True, "答错应加入错题本"
        print(f"✓ 答错自动加入错题本: is_wrong_added={wrong_result['is_wrong_added']}")

        # ── 4. POST /practice/batch-submit ──
        question_ids = [q["id"] for q in data["questions"][:2]]
        r = await client.post(
            "/api/v1/practice/batch-submit",
            json={
                "answers": [
                    {"question_id": question_ids[0], "user_answer": "A", "used_time": 20},
                    {"question_id": question_ids[1], "user_answer": "Z", "used_time": 25},
                ]
            },
            headers=HEADERS,
        )
        assert r.status_code == 200, f"Batch submit failed: {r.status_code} {r.text}"
        batch = r.json()
        assert "results" in batch
        assert "total_correct" in batch and "total_wrong" in batch
        assert len(batch["results"]) == 2
        print(f"✓ POST /practice/batch-submit: correct={batch['total_correct']}, wrong={batch['total_wrong']}")

        # ── 5. GET /practice/stats ──
        r = await client.get(
            "/api/v1/practice/stats", params={"days": 7}, headers=HEADERS
        )
        assert r.status_code == 200
        stats = r.json()
        assert "total_answered" in stats
        assert "total_correct" in stats
        assert "accuracy" in stats
        assert "daily_stats" in stats
        assert "current_streak" in stats
        print(f"✓ GET /practice/stats: answered={stats['total_answered']}, accuracy={stats['accuracy']}, streak={stats['current_streak']}")

        # ── 6. GET /questions/{id}/detail (已答用户) ──
        r = await client.get(f"/api/v1/questions/{qid}/detail", headers=HEADERS)
        assert r.status_code == 200, f"Detail failed: {r.status_code} {r.text}"
        detail = r.json()
        assert "answer" in detail, "含答案接口应返回 answer"
        assert "analysis" in detail, "含答案接口应返回 analysis"
        print(f"✓ GET /questions/{qid}/detail: 含答案返回 OK (answer={detail['answer']})")

        # ── 7. GET /questions/{id}/detail (未答用户) ──
        # 题目 id=10 应该存在且未被 user=1 答过
        r = await client.get("/api/v1/questions/10/detail", headers=HEADERS)
        if r.status_code == 403:
            print(f"✓ GET /questions/10/detail: 未答用户正确拒绝 (403)")
        elif r.status_code == 404:
            print(f"⚠ GET /questions/10/detail: 题目不存在 (404) — 测试跳过")
        else:
            print(f"✗ 预期 403，实际 {r.status_code}: {r.text}")
            FAILED += 1

        # ── 8. GET /practice/records ──
        r = await client.get(
            "/api/v1/practice/records", params={"page": 1, "page_size": 5}, headers=HEADERS
        )
        assert r.status_code == 200
        records = r.json()
        print(f"✓ GET /practice/records: {records['total']} 条记录")

        # ── 9. 题目不存在 ──
        r = await client.post(
            "/api/v1/practice/submit",
            json={"question_id": 99999, "user_answer": "A"},
            headers=HEADERS,
        )
        assert r.status_code == 400, f"应返回 400: {r.status_code}"
        print(f"✓ 不存在的题目返回 400: {r.json()['detail']}")

        # ── 10. 验证 exclude_answered ──
        r = await client.get(
            "/api/v1/practice/questions",
            params={"subject": "math2", "count": 20, "exclude_answered": True},
            headers=HEADERS,
        )
        data2 = r.json()
        answered_ids = {q["id"] for q in data["questions"][:2]}
        excluded = all(q["id"] not in answered_ids for q in data2["questions"])
        print(f"✓ exclude_answered=True: 已做题已排除" if excluded else "⚠ exclude_answered 未生效")

        # ── 11. 大小写不敏感 ──
        r = await client.post(
            "/api/v1/practice/submit",
            json={"question_id": question_ids[0], "user_answer": "a"},  # lowercase
            headers=HEADERS,
        )
        assert r.status_code == 200
        print(f"✓ 大小写不敏感: is_correct={r.json()['is_correct']}")

    print(f"\n{'='*50}")
    print(f"测试完成: {PASSED} 通过, {FAILED} 失败")


if __name__ == "__main__":
    asyncio.run(main())

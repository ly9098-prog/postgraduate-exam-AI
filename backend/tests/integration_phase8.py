"""阶段八：OCR / 扫描版 PDF 导入 集成测试

覆盖：
1. clean_ocr_text 文本清洗规则（断行、乱码、空格、空行）
2. pdf_classifier.classify_pages 正确区分文本/图片页
3. has_any_ocr_pages / get_pixmap
4. ocr_service.ocr_pages 并发与单页失败跳过（PaddleOCR 用 stub）
5. import_service._extract_pdf_text：文本型 PDF 走文本通道，**不**触发 OCR
6. import_service._extract_pdf_text：扫描版 PDF 自动走 OCR 通道
7. OCR_ENABLED=False 时扫描版 PDF 完全不走 OCR（关键回滚开关）
8. import_pdf 端到端（文本型 + 扫描版均能入库 question_imports）
9. /api/v1/import/upload 上传 PDF 走完整链路
10. 与阶段七的兼容性：导入后仍是 status=pending，question_id=None，无回归

运行：
  cd backend
  python3 -m tests.integration_phase8

依赖：
- PyMuPDF（必须，用于构造测试 PDF + 真实跑 classify/render 流程）
- paddleocr：**不需要真实安装**，本测试通过 monkey-patch
  ocr_service._ocr_instance 注入 stub，避免拉重型依赖。
"""
import asyncio
import io
import os
import sys
import uuid

_TEST_DB_PATH = f"./_test_phase8_{uuid.uuid4().hex[:6]}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ.setdefault("APP_ENV", "test")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # noqa: E402  PyMuPDF
import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import Base, async_session, engine  # noqa: E402
from app.features import question_pipeline as import_service
from app.main import app as fastapi_app  # noqa: E402
from app.models.ai_chat import AiChat  # noqa: E402,F401
from app.models.ai_generation_log import AiGenerationLog  # noqa: E402,F401
from app.models.answer_behavior import AnswerBehavior  # noqa: E402,F401
from app.models.practice_record import PracticeRecord  # noqa: E402,F401
from app.models.question import Question  # noqa: E402,F401
from app.models.question_import import QuestionImport  # noqa: E402,F401
from app.models.tag import Tag  # noqa: E402,F401

# 注册所有 model 到 metadata（保持与 alembic env 一致）
from app.models.user import User  # noqa: E402,F401
from app.models.wrong_question import WrongQuestion  # noqa: E402,F401
from app.services import ocr_service, pdf_classifier  # noqa: E402

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


# ───────────────────────────── 测试用 PDF 构造 ─────────────────────────────


def _build_text_pdf() -> bytes:
    """构造一份 2 页的文本型 PDF，包含 2 道选择题。"""
    doc = fitz.open()
    page1 = doc.new_page()
    text1 = (
        "1. 设函数 f(x)=x^2, 则 f'(1) 的值为?\n"
        "A. 1\n"
        "B. 2\n"
        "C. x\n"
        "D. 2x\n"
        "答案: B\n"
        "解析: f'(x)=2x, 代入 x=1 得 2.\n"
    )
    page1.insert_text((50, 80), text1, fontsize=11, fontname="china-s")

    page2 = doc.new_page()
    text2 = (
        "2. 不定积分 ∫ 2x dx 的结果是?\n"
        "A. x\n"
        "B. x^2 + C\n"
        "C. 2 + C\n"
        "D. 2x^2 + C\n"
        "答案: B\n"
        "解析: x^2 的导数是 2x, 故反过来.\n"
    )
    page2.insert_text((50, 80), text2, fontsize=11, fontname="china-s")

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _build_scanned_pdf() -> bytes:
    """构造一份扫描版 PDF：只塞图片，不嵌入文本层。
    用纯色 PNG 占位，page.get_text() 应为空 → 触发 OCR 通道。
    """
    doc = fitz.open()
    # 1 像素纯灰 PNG（简短可内嵌的 base64）
    import base64
    one_px_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    for _ in range(3):
        page = doc.new_page(width=400, height=300)
        rect = fitz.Rect(0, 0, 400, 300)
        page.insert_image(rect, stream=one_px_png)
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


# ───────────────────────────── PaddleOCR Stub ─────────────────────────────


class _FakeOCR:
    """伪造 PaddleOCR：根据 page_index 返回不同的题干文本。"""
    def __init__(self, page_texts: list[str] | None = None):
        self.calls = 0
        self.last_shape = None
        self._page_texts = page_texts or [
            "1. 扫描题 第一题。下列哪项正确?\nA. 选项一\nB. 选项二\nC. 选项三\nD. 选项四\n参考答案: A",
            "2. 扫描题 第二题。导数公式中, 正确的是?\nA. 错误\nB. 正确\nC. 不确定\nD. 都不对\n参考答案: B",
            "3. 扫描题 第三题。计算下列极限 lim x->0 sin(x)/x 等于?\nA. 0\nB. 1\nC. 无穷\nD. 不存在\n参考答案: B",
        ]

    def ocr(self, img_array, cls=True):
        self.calls += 1
        self.last_shape = img_array.shape
        # 用 calls 计数轮流给不同文本（模拟并发各页不同结果）
        idx = (self.calls - 1) % len(self._page_texts)
        txt = self._page_texts[idx]
        lines = [[[[0, 0], [1, 0], [1, 1], [0, 1]], (line, 0.95)] for line in txt.split("\n")]
        return [lines]


class _FailingOCR:
    """每页都抛异常的 OCR，用于验证失败跳过逻辑。"""
    def ocr(self, img_array, cls=True):
        raise RuntimeError("simulated OCR engine failure")


def _install_fake_ocr(impl) -> object:
    """把 fake OCR 注入 ocr_service 单例位，并返回原值用于恢复。"""
    original = ocr_service._ocr_instance
    ocr_service._ocr_instance = impl
    return original


def _restore_ocr(original) -> None:
    ocr_service._ocr_instance = original


# ───────────────────────────── DB / 登录工具 ─────────────────────────────


async def setup_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def teardown_db() -> None:
    await engine.dispose()
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)


async def login(client: httpx.AsyncClient) -> str:
    res = await client.post("/api/v1/auth/login", json={"code": "phase8-test"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def case_ocr_image_preprocesses_small_image() -> None:
    print("\n[4] ocr_image 小图预处理")
    import base64

    valid_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    fake = _FakeOCR(["1. 题干\nA. 选项"])
    original = _install_fake_ocr(fake)
    try:
        text = ocr_service.ocr_image(valid_png)
        check("小图 OCR 返回文本", "题干" in text, repr(text))
        check("小图被放大到可识别宽度", fake.last_shape[1] >= 1000, f"shape={fake.last_shape}")
    finally:
        _restore_ocr(original)


def case_ocr_pages_with_boxes_preprocesses_small_image() -> None:
    print("\n[5] ocr_pages_with_boxes 小图预处理")
    import base64

    valid_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    fake = _FakeOCR(["1. 题干\nA. 选项"])
    original = _install_fake_ocr(fake)
    try:
        results = ocr_service.ocr_pages_with_boxes([(0, valid_png)])
        check("含框 OCR 返回结果", 0 in results and results[0].text, str(results))
        check("含框 OCR 也会放大小图", fake.last_shape[1] >= 1000, f"shape={fake.last_shape}")
    finally:
        _restore_ocr(original)




def case_clean_ocr_text() -> None:
    print("\n[1] clean_ocr_text 文本清洗")
    f = ocr_service.clean_ocr_text

    # 1.1 连续空格
    check("连续空格压缩为一个", f("a    b") == "a b", repr(f("a    b")))
    # 1.2 多空行
    check("3 个以上换行压缩为 2 个",
          f("a\n\n\n\nb") == "a\n\nb", repr(f("a\n\n\n\nb")))
    # 1.3 中文断行合并
    check("断行中文合并", f("第\n一章") == "第一章", repr(f("第\n一章")))
    # 1.4 行首行尾空格去除
    check("行首尾空格去除", f("  hello  \n  world  ") == "hello\nworld",
          repr(f("  hello  \n  world  ")))
    # 1.5 空输入安全
    check("空输入返回空", f("") == "" and f(None) == "", "")  # type: ignore
    # 1.6 含乱码（非中/英/标点字符）
    out = f("正常\x01\x02\x03文本")
    check("剥离不可打印乱码", "正常" in out and "文本" in out and "\x01" not in out, repr(out))
    # 1.7 题目选项与答案之间保留换行
    out = f("D. 选项四参考答案: A")
    check("答案标记独立成行", "\n参考答案: A" in out, repr(out))


def case_classify_pages_text_pdf(text_pdf: bytes) -> None:
    print("\n[2] classify_pages：文本型 PDF 不需要 OCR")
    classified = pdf_classifier.classify_pages(text_pdf)
    check("classify 返回 2 页", len(classified) == 2, f"len={len(classified)}")
    check("第 1 页 needs_ocr=False",
          classified[0]["needs_ocr"] is False,
          f"needs_ocr={classified[0]['needs_ocr']}")
    # PyMuPDF 用 china-s CJK 字体渲染时会在字符间插入空格，比较时去掉空白
    page1_text_compact = "".join(classified[0]["text"].split())
    check("第 1 页 text 含题干关键词",
          "f(x)" in page1_text_compact or "x^2" in page1_text_compact,
          repr(classified[0]["text"][:80]))
    check("文本型页不保留 _page 引用",
          classified[0]["_page"] is None,
          f"_page={classified[0]['_page']}")
    check("has_any_ocr_pages=False",
          pdf_classifier.has_any_ocr_pages(classified) is False, "")


def case_classify_pages_scanned_pdf(scan_pdf: bytes) -> None:
    print("\n[3] classify_pages：扫描版 PDF 标记需要 OCR")
    classified = pdf_classifier.classify_pages(scan_pdf)
    check("扫描版 classify 返回 3 页", len(classified) == 3, f"len={len(classified)}")
    check("全部页 needs_ocr=True",
          all(p["needs_ocr"] for p in classified),
          f"flags={[p['needs_ocr'] for p in classified]}")
    check("扫描页 text 为空",
          all(p["text"] == "" for p in classified),
          f"texts={[len(p['text']) for p in classified]}")
    check("扫描页保留 _page 引用",
          all(p["_page"] is not None for p in classified), "")
    check("has_any_ocr_pages=True",
          pdf_classifier.has_any_ocr_pages(classified) is True, "")

    # 渲染一页为 PNG
    png = pdf_classifier.get_pixmap(classified[0]["_page"])
    check("get_pixmap 返回 PNG 字节",
          isinstance(png, bytes) and png.startswith(b"\x89PNG"),
          f"head={png[:8]!r}")


def case_ocr_pages_concurrent() -> None:
    print("\n[4] ocr_pages 并发 + 单页失败跳过")
    # 准备一张合法的 1×1 PNG（必须能被 PIL.Image.open 解码，否则
    # _ocr_one_page 在 PIL 阶段就会异常掉，根本走不到 stub）
    import base64
    valid_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    # 4.1 正常并发
    fake = _FakeOCR()
    original = _install_fake_ocr(fake)
    try:
        results = ocr_service.ocr_pages([(0, valid_png), (1, valid_png), (2, valid_png)])
        check("返回 3 页结果", len(results) == 3, f"len={len(results)}")
        check("每页都有非空文本",
              all(results.get(i) for i in (0, 1, 2)),
              f"results={ {k: len(v) for k, v in results.items()} }")
    finally:
        _restore_ocr(original)

    # 4.2 OCR 引擎抛异常 → 该页返回空字符串，不崩溃
    original = _install_fake_ocr(_FailingOCR())
    try:
        results = ocr_service.ocr_pages([(0, valid_png), (1, valid_png)])
        check("失败 OCR 不抛异常", isinstance(results, dict), f"results={results}")
        check("失败页文本为空",
              results.get(0) == "" and results.get(1) == "",
              f"results={results}")
    finally:
        _restore_ocr(original)

    # 4.3 空输入
    check("空输入返回空 dict", ocr_service.ocr_pages([]) == {}, "")


def case_extract_text_only(text_pdf: bytes) -> None:
    print("\n[5] _extract_pdf_text：文本型不触发 OCR")
    fake = _FakeOCR()
    original = _install_fake_ocr(fake)
    try:
        text = import_service._extract_pdf_text(text_pdf)
        compact = "".join(text.split())
        check("提取到完整文本",
              "f(x)" in compact and "不定积分" in compact,
              repr(text[:160]))
        check("文本型 PDF 完全不调用 OCR",
              fake.calls == 0, f"OCR 调用次数={fake.calls}")
    finally:
        _restore_ocr(original)


def case_extract_text_scanned(scan_pdf: bytes) -> None:
    print("\n[6] _extract_pdf_text：扫描版自动走 OCR 通道")
    fake = _FakeOCR()
    original = _install_fake_ocr(fake)
    # 确保 OCR 总开关打开
    saved_enabled = settings.OCR_ENABLED
    settings.OCR_ENABLED = True
    try:
        text = import_service._extract_pdf_text(scan_pdf)
        check("扫描版 PDF OCR 调用次数==页数",
              fake.calls == 3, f"OCR 调用次数={fake.calls}")
        check("OCR 输出已合并到全文",
              "扫描题" in text and "答案" in text, repr(text[:160]))
    finally:
        settings.OCR_ENABLED = saved_enabled
        _restore_ocr(original)


def case_extract_text_ocr_disabled(scan_pdf: bytes) -> None:
    print("\n[7] OCR_ENABLED=False 时扫描版 PDF 不触发 OCR（关键开关）")
    fake = _FakeOCR()
    original = _install_fake_ocr(fake)
    saved_enabled = settings.OCR_ENABLED
    settings.OCR_ENABLED = False
    try:
        text = import_service._extract_pdf_text(scan_pdf)
        check("关闭后 OCR 调用次数=0", fake.calls == 0,
              f"OCR 调用次数={fake.calls}")
        check("关闭后扫描版返回空文本",
              text.strip() == "",
              f"text head={text[:80]!r}")
    finally:
        settings.OCR_ENABLED = saved_enabled
        _restore_ocr(original)


async def case_import_pdf_text_e2e(text_pdf: bytes) -> None:
    print("\n[8] import_pdf 端到端：文本型 PDF 入库")
    async with async_session() as db:
        batch_id, total = await import_service.import_pdf(db, text_pdf, "text.pdf")
        check("import_pdf 返回 batch_id 前缀 BATCH_",
              batch_id.startswith("BATCH_"), f"batch_id={batch_id}")
        check("解析出至少 2 题", total >= 2, f"total={total}")

    async with async_session() as db:
        rows = (await db.execute(
            select(QuestionImport).where(QuestionImport.batch_id == batch_id)
        )).scalars().all()
        check("入库行数与返回 total 一致",
              len(rows) == total, f"db={len(rows)} total={total}")
        for r in rows:
            check(f"qi#{r.id} source_type=pdf",
                  r.source_type == "pdf", f"source_type={r.source_type}")
            check(f"qi#{r.id} status=pending",
                  r.status == "pending", f"status={r.status}")
            check(f"qi#{r.id} question_id 未关联",
                  r.question_id is None, f"question_id={r.question_id}")
        # 选择题应解析出 answer
        answers = [r.parsed_answer for r in rows]
        check("至少一题解析出 answer", any(a for a in answers), f"answers={answers}")


async def case_import_pdf_scanned_e2e(scan_pdf: bytes) -> None:
    print("\n[9] import_pdf 端到端：扫描版 PDF 经 OCR 入库")
    fake = _FakeOCR()
    original = _install_fake_ocr(fake)
    saved_enabled = settings.OCR_ENABLED
    settings.OCR_ENABLED = True
    try:
        async with async_session() as db:
            batch_id, total = await import_service.import_pdf(db, scan_pdf, "scan.pdf")
            check("扫描版解析出题目数 >=1",
                  total >= 1, f"total={total}")
            check("OCR 被调用了页数次",
                  fake.calls == 3, f"OCR 调用次数={fake.calls}")

        async with async_session() as db:
            rows = (await db.execute(
                select(QuestionImport).where(QuestionImport.batch_id == batch_id)
            )).scalars().all()
            check("扫描版入库行数与返回一致",
                  len(rows) == total, f"db={len(rows)} total={total}")
            for r in rows:
                check(f"扫描 qi#{r.id} source_type=pdf",
                      r.source_type == "pdf", f"source_type={r.source_type}")
                check(f"扫描 qi#{r.id} status=pending",
                      r.status == "pending", f"status={r.status}")
            # OCR 文本含"扫描题"应被切到题干里
            stems = [(r.parsed_content or {}).get("text", "") for r in rows]
            check("题干含 OCR 关键词 '扫描题'",
                  any("扫描题" in s for s in stems),
                  f"stems={stems[:3]}")
    finally:
        settings.OCR_ENABLED = saved_enabled
        _restore_ocr(original)


async def case_import_pdf_scanned_disabled(scan_pdf: bytes) -> None:
    print("\n[10] OCR_ENABLED=False 时扫描版应抛 ValueError（无文本可解析）")
    fake = _FakeOCR()
    original = _install_fake_ocr(fake)
    saved_enabled = settings.OCR_ENABLED
    settings.OCR_ENABLED = False
    try:
        async with async_session() as db:
            raised = False
            try:
                await import_service.import_pdf(db, scan_pdf, "scan_off.pdf")
            except ValueError as e:
                raised = True
                check("异常信息提示 OCR 均无结果",
                      "OCR" in str(e) or "文本" in str(e), f"msg={e}")
            check("关闭 OCR + 扫描版 → 抛 ValueError",
                  raised, "未抛异常")
            check("关闭后未调用 OCR",
                  fake.calls == 0, f"calls={fake.calls}")
    finally:
        settings.OCR_ENABLED = saved_enabled
        _restore_ocr(original)


async def case_upload_api_text_pdf(client: httpx.AsyncClient, headers: dict, text_pdf: bytes) -> None:
    print("\n[11] /api/v1/import/upload：文本型 PDF 走完整 API")
    files = {"file": ("api_text.pdf", text_pdf, "application/pdf")}
    res = await client.post("/api/v1/import/upload", files=files, headers=headers)
    check("upload 200", res.status_code == 200, res.text)
    body = res.json()
    check("source_type=pdf", body.get("source_type") == "pdf", str(body))
    check("total >= 2", body.get("total", 0) >= 2, str(body))
    check("batch_id 前缀 BATCH_",
          body.get("batch_id", "").startswith("BATCH_"), str(body))

    # 批次详情可查
    bid = body["batch_id"]
    res = await client.get(f"/api/v1/import/batches/{bid}", headers=headers)
    check("/import/batches/{id} 200", res.status_code == 200, res.text)


async def case_upload_api_scanned_pdf(client: httpx.AsyncClient, headers: dict, scan_pdf: bytes) -> None:
    print("\n[12] /api/v1/import/upload：扫描版 PDF（OCR stub）走完整 API")
    fake = _FakeOCR()
    original = _install_fake_ocr(fake)
    saved_enabled = settings.OCR_ENABLED
    settings.OCR_ENABLED = True
    try:
        files = {"file": ("api_scan.pdf", scan_pdf, "application/pdf")}
        res = await client.post("/api/v1/import/upload", files=files, headers=headers)
        check("scan upload 200", res.status_code == 200, res.text)
        body = res.json()
        check("scan 走 OCR 解出题目", body.get("total", 0) >= 1, str(body))
        check("OCR 调用计数与扫描页数一致",
              fake.calls == 3, f"calls={fake.calls}")
    finally:
        settings.OCR_ENABLED = saved_enabled
        _restore_ocr(original)


def case_corrupt_pdf() -> None:
    print("\n[13] 损坏 PDF：classify_pages 应抛异常（不静默吞）")
    raised = False
    try:
        pdf_classifier.classify_pages(b"not a pdf at all")
    except Exception:
        raised = True
    check("损坏 PDF 触发异常", raised, "未抛")


# ───────────────────────────── 主流程 ─────────────────────────────


async def main() -> int:
    print("=" * 60)
    print("阶段八：OCR / 扫描版 PDF 集成测试")
    print(f"数据库：{_TEST_DB_PATH}")
    print(f"OCR_ENABLED 当前默认值：{settings.OCR_ENABLED}")
    print("=" * 60)

    await setup_db()

    text_pdf = _build_text_pdf()
    scan_pdf = _build_scanned_pdf()
    print(f"测试 PDF 构造完成：text={len(text_pdf)}B, scanned={len(scan_pdf)}B")

    # 纯函数测试
    case_clean_ocr_text()
    case_classify_pages_text_pdf(text_pdf)
    case_classify_pages_scanned_pdf(scan_pdf)
    case_ocr_image_preprocesses_small_image()
    case_ocr_pages_with_boxes_preprocesses_small_image()
    case_ocr_pages_concurrent()
    case_extract_text_only(text_pdf)
    case_extract_text_scanned(scan_pdf)
    case_extract_text_ocr_disabled(scan_pdf)
    case_corrupt_pdf()

    # DB / 服务层 / API
    await case_import_pdf_text_e2e(text_pdf)
    await case_import_pdf_scanned_e2e(scan_pdf)
    await case_import_pdf_scanned_disabled(scan_pdf)

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
        token = await login(client)
        headers = {"Authorization": f"Bearer {token}"}
        await case_upload_api_text_pdf(client, headers, text_pdf)
        await case_upload_api_scanned_pdf(client, headers, scan_pdf)

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

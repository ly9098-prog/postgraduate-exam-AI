# 数学公式图片化 — 分阶段执行计划（修订版 v1.2）

> 配套文档：`docs/architecture/MATH_IMAGE_ARCHITECTURE.md`（架构决策，冻结版 v1.2）
> 总工期估算：14-17 天

---

## Stage 0：Feature Flag + 存储后端骨架

> **前置阶段，必须在 Stage 1 之前完成。**

### 目标

1. 建立后端 Feature Flag（`MATH_IMAGE_RENDER_ENABLED`）
2. 实现 `StorageBackend` 抽象及开发用 `LocalFileStorage`
3. 建立前端 Feature Flag（`config.enableMathImage`）
4. 配置 FastAPI 静态文件服务（开发用）
5. 建立 `PUBLIC_BASE_URL` 配置，解决真机 URL 问题

### 输入

- 现有代码库（不依赖任何 Stage 1+ 的新模块）

### 输出

- `MATH_IMAGE_RENDER_ENABLED=true/false` 可控制后端图片化路径
- `config.enableMathImage = false` 时前端强制走旧渲染路径
- `http://{PUBLIC_BASE_URL}/static/formulas/` 可访问上传的 PNG（开发/真机均可配置）

### 修改文件

- **修改** `backend/app/core/config.py`
  - 新增 `MATH_IMAGE_RENDER_ENABLED: bool = False`
  - 新增 `PUBLIC_BASE_URL: str = "http://localhost:8000"`（真机调试时改为 `http://192.168.x.x:8000`）
  - 新增 `STORAGE_BACKEND: str = "local"`（`"local"` 或 `"cos"`）
- **新建** `backend/app/services/storage_backend.py`
  - `class StorageBackend(ABC)` — `async def upload(filename: str, data: bytes) -> str`
  - `class LocalFileStorage(StorageBackend)` — 保存到 `backend/static/formulas/{YYYYMM}/`，返回 `{PUBLIC_BASE_URL}/static/formulas/{YYYYMM}/{filename}`
  - `class COSStorage(StorageBackend)` — 占位，`raise NotImplementedError`
  - `def get_storage() -> StorageBackend` — 工厂函数，按 `settings.STORAGE_BACKEND` 选择
- **修改** `backend/app/main.py`
  - 挂载 `StaticFiles(directory="static/formulas", html=False)` 到 `/static/formulas`
  - 启动时 `os.makedirs("static/formulas", exist_ok=True)`
- **新建** `backend/static/formulas/.gitkeep`
- **修改** `miniprogram/config.js`
  - 新增 `enableMathImage: false`（默认关闭）
- **修改** `miniprogram/pages/practice/practice.js`
  - `onLoad` 中读取 `config.enableMathImage`，写入 `this.data.enableMathImage`

### 验收标准

1. `MATH_IMAGE_RENDER_ENABLED=false`（默认）时，现有所有测试通过，无任何行为变化
2. `LocalFileStorage.upload("test.png", png_bytes)` 后 `backend/static/formulas/` 目录中出现文件
3. `GET http://localhost:8000/static/formulas/{YYYYMM}/test.png` 返回 200 + PNG
4. `PUBLIC_BASE_URL=http://192.168.1.100:8000` 时，`LocalFileStorage.upload()` 返回 URL 以该地址开头
5. `miniprogram/config.js` 中 `enableMathImage: false` 时，practice 页面走旧 mp-html 路径
6. Alembic 不受影响（无 DB 变更）

### 回归测试范围

- 现有所有测试（`pytest backend/tests/`）不报错
- 手动验证：随机刷题、错题本、导入流程均正常

---

## Stage 1：数学区域检测

### 目标

实现 `MathRegionDetector`：读取 PDF 页面，基于 Unicode 数学字符区间检测数学公式 bbox。

### 输入

- `fitz.Page` 对象（pymupdf）

### 输出

```python
List[MathRegion]  # image_url = None（截图在 Stage 2 完成）
```

### 修改文件

- **新建** `backend/app/services/math_region_detector.py`
  - `detect_page(page: fitz.Page) -> List[MathRegion]`
  - `detect_document(doc: fitz.Document, pages: list[int] | None) -> dict[int, List[MathRegion]]`
  - 实现架构文档 §2.1 主路径（Unicode 字符区间 + 字体名辅助）
  - 实现 §2.3 区域扩展（6pt padding，12pt 合并阈值）
  - 实现 §2.4 区域分类（INLINE / DISPLAY / MIXED）
  - 任何异常 → 返回空列表，记录 warning，不抛出
- **新建** `backend/tests/test_math_region_detector.py`
  - 用自制测试 PDF T01、T02、T03（非版权题，用 LaTeX/Word 生成，精简版 3-5 页）
  - 覆盖：无公式页、有公式页、纯扫描页（无文字层）
- **新建** `backend/tests/fixtures/README.md`
  - 说明各测试 PDF 的生成方式（不存真题，避免版权问题）
- **修改** `backend/requirements.txt`
  - 确认 `pymupdf>=1.23` 已在依赖中

### 验收标准

1. T01（LaTeX 自制，含积分/极限/矩阵）：召回率 ≥ 60%
2. T02（MathType 导出）：召回率 ≥ 50%
3. T03（ASCII 表达式）：误检率 ≤ 10%
4. 无公式页面：误检 = 0
5. 扫描版 PDF（无文字层）：返回空列表，不抛异常
6. 任意 PDF 处理不报 500，异常降级正常

### 回归测试范围

- `tests/test_math_region_detector.py`（新建）
- 现有 `tests/test_pdf_parser.py` 不应报错
- Stage 0 验收标准继续通过

---

## Stage 2：公式截图系统

### 目标

实现 `FormulaImageCropper`：根据 MathRegion bbox 截图，上传到 StorageBackend，返回填充了 `image_url` 的 MathRegion 列表。

### 输入

```python
doc: fitz.Document
regions: List[MathRegion]
storage: StorageBackend   # 从 get_storage() 获取
import_id: int            # 用于 URL 命名（question_imports.id）
```

### 输出

```python
List[MathRegion]  # image_url 已填充为绝对 HTTP URL
```

### 修改文件

- **新建** `backend/app/services/formula_image_cropper.py`
  - `crop_region(page: fitz.Page, region: MathRegion) -> bytes`
    - DPI：INLINE=144，DISPLAY=240，MIXED=144
    - padding 扩展 6pt，PNG 格式
  - `async def crop_and_upload(doc, regions, storage, import_id) -> List[MathRegion]`
    - 文件名：`{YYYYMM}/{import_id}_{page}_{content_hash}.png`（`content_hash=md5(png_bytes)[:8]`）
    - 单图失败时跳过（`region.image_url` 保持 None），不中断批量处理
    - 返回含 `image_url` 的 MathRegion 列表
- **新建** `backend/tests/test_formula_image_cropper.py`

### 验收标准

1. 对检测出 3 个 MathRegion 的页面，`crop_and_upload` 返回 3 个已填充 `image_url` 的 MathRegion
2. 返回的 URL 均可通过 HTTP GET 访问（`LocalFileStorage` 场景）
3. PNG 图片实际像素尺寸 ≥ bbox 原始尺寸（有 padding）
4. 单图上传失败时，其余图片正常返回，不抛异常
5. 单页 10 个公式截图 + 上传总耗时 < 3 秒（本地）
6. URL 格式符合命名规范：路径含 `{YYYYMM}/` 前缀，无双重 `formulas/formulas/`
7. 相同 PNG 内容（同一公式）产生相同文件名（content_hash 相同）

### 回归测试范围

- `tests/test_formula_image_cropper.py`（新建）
- Stage 0、1 验收标准继续通过

---

## Stage 3：混合题结构升级

### 目标

1. 实现 `HybridContentBuilder`
2. 升级 PDF 导入 Pipeline（BackgroundTask，per-import 调度）
3. `_parse_pdf()` 切题时记录 `page_num`
4. 扩展 `question_imports` 表（`math_regions` 列）
5. 新增 math-preview API

### 输入

- PDF 文件上传（触发 `import_pdf()`）
- `MATH_IMAGE_RENDER_ENABLED=true`（否则跳过 BackgroundTask）

### 输出

```python
# QuestionImport.parsed_content（当有公式时）
{
  "text": "...$\\latex$...",   # 公式用 alt 内联
  "segments": [...],
  "render_mode": "segments"
}
```

### 修改文件

- **新建** `backend/app/services/hybrid_content_builder.py`
  - `build(text: str, regions: List[MathRegion]) -> dict`
  - 输出符合架构文档 §3.3 的 content JSON
  - `content.text` 拼接规则：公式位置用 `$<alt>$` 内联（LaTeX 字符串）
  - 无 MathRegion 时：只生成 `{"text": "..."}` 无 segments
- **修改** `backend/app/services/import_service.py`
  - `_parse_pdf()` 切题循环内追踪 `page_num`，存入每题的 `raw_data["page_num"]`
    - 一题跨多页时，取题目首行所在页
  - `import_pdf()` 改为：
    1. `await file.read()` → 写 `NamedTemporaryFile(delete=False, suffix='.pdf')` 得 `tmp_path`
    2. 用 `tmp_path` 调用 `_parse_pdf()`（现有逻辑改为从路径读）
    3. 写 QuestionImport，返回响应
    4. 若 `settings.MATH_IMAGE_RENDER_ENABLED`：注册 `_run_math_pipeline(batch_id, tmp_path, db)` 为 BackgroundTask；否则 `os.unlink(tmp_path)`
  - 新增 `_run_math_pipeline(batch_id, tmp_pdf_path, db)`（见架构文档 §1.4）
  - Excel 导入路径（`import_excel()`）**完全不修改**
- **新建** `backend/alembic/versions/XXXX_add_math_regions.py`
  - `question_imports` 增加 `math_regions` JSON 列
  - `upgrade` 和 `downgrade` 均可执行
- **修改** `backend/app/models/question_import.py`
  - 新增 `math_regions: Mapped[dict | None] = mapped_column(JSON, nullable=True)`
- **修改** `backend/app/api/v1/import.py`
  - 新增 `GET /api/v1/import/math-preview/{import_id}`（需 admin token）
  - 响应中 `has_math`、`formula_count` 通过遍历 `parsed_content.segments` 计算

### 验收标准

1. 对含公式 PDF（`MATH_IMAGE_RENDER_ENABLED=true`），BackgroundTask 执行后 `parsed_content` 含 `segments`
2. `segments` 中 `math_image.url` 可通过 HTTP GET 访问
3. `content.text` 中公式位置用 `$<alt>$` 占位（而非空白或删除）
4. 对无公式 PDF，`parsed_content` 无 `segments`，与旧路径一致
5. 对 Excel 导入，行为与修改前完全一致
6. 公式检测/截图失败时，不报 500，QuestionImport 保持纯文本内容，BackgroundTask 不影响主流程
7. `GET /import/math-preview/{import_id}` 返回正确预览
8. Alembic `upgrade head` 和 `downgrade` 均可干净执行
9. `tmp_pdf_path` 在 BackgroundTask 完成后（包括异常情况）被清理，无文件泄漏

### 回归测试范围

- `tests/test_question_pipeline.py`（原有测试必须全部通过）
- `tests/test_hybrid_content_builder.py`（新建）
- 手动测试：Excel 导入 5 题，刷题页渲染正常
- 手动测试：`MATH_IMAGE_RENDER_ENABLED=false` 时 PDF 导入行为与修改前一致

---

## Stage 4：前端图片渲染

### 目标

实现 `math-question` 小程序组件；改造 `practice` 和 `wrong-book` 页面支持双路径渲染。

### 输入

- `currentQuestion.content`（来自现有接口，无需改动）
- `config.enableMathImage`（Stage 0 已建立）

### 输出

- `config.enableMathImage = true` 且 `render_mode = "segments"` 时：显示公式截图
- 其他情况：完全同修改前

### 修改文件

- **新建** `miniprogram/components/math-question/math-question.wxml`（见架构文档 §4.2）
- **新建** `miniprogram/components/math-question/math-question.wxss`（见 §4.2）
- **新建** `miniprogram/components/math-question/math-question.js`（见 §4.2，含 observers + `onImgError`）
- **新建** `miniprogram/components/math-question/math-question.json`
- **新建** `miniprogram/__mocks__/math-question-fixtures.js`
  - 包含 5-10 个典型 segments 用例（纯文本段、inline 公式、display 公式、图片加载失败场景）
  - 用于 Stage 4 并行开发时的 mock 数据
- **修改** `miniprogram/pages/practice/practice.wxml` — 双路径渲染（见 §4.3）
- **修改** `miniprogram/pages/practice/practice.json` — 注册 `math-question` 组件
- **修改** `miniprogram/pages/wrong-book/wrong-book.wxml` — 同上
- **修改** `miniprogram/pages/wrong-book/wrong-book.json` — 注册组件

### 验收标准

1. `config.enableMathImage = false` 时，旧题/新题渲染效果与修改前完全一致
2. `config.enableMathImage = true` 时，含 `segments` 的新题正确显示公式截图
3. Display 公式图片宽度自适应屏幕，不溢出（`mode="widthFix"`）
4. Inline 公式图片与周围文字对齐（inline-block wrapper + `vertical-align: middle`）
5. 图片加载失败时（`binderror` 触发），切换为 `alt` 文本展示，不出现白块
6. 切换题目后，上一题的 `_error` 状态不会污染新题（observers 重置）
7. 开发者工具模拟器验证通过（iPhone 14 Pro、Pixel 5 两个尺寸）
8. **真机验证**（配置 `PUBLIC_BASE_URL` 为局域网 IP）：iOS 15+ 真机 1 台 + Android 8+ 真机 1 台
9. 随机刷 20 题（含旧题），无白屏/崩溃/排版错位

### 运维任务

- 在微信公众平台配置生产 CDN 域名为"downloadFile 合法域名"（生产上线前必须完成）

### 回归测试范围

- 手动回归：随机刷 20 题（旧题），渲染正常
- 手动回归：错题本页面正常展示
- 手动回归：`config.enableMathImage = false` 时所有功能正常

---

## Stage 5：渐进式 OCR 升级（扫描版 + 审核界面增强）

### 目标

1. 扫描版 PDF 的公式检测接入 PaddleOCR 检测框聚类
2. `ocr_service.py` 新增返回 boxes 的方法（不改旧签名）
3. 审核界面增加"含公式"标记和预览弹窗

### 输入

- 扫描版 PDF（pypdf 提取文本 < 100 字符，已触发 PaddleOCR）

### 聚类算法规范

1. **水平投影分行**：按检测框 y 中心坐标，差值 < 行高均值 × 0.6 视为同行
2. **行内 DBSCAN 聚类**：eps = 15px，min_samples = 1；框间距 < eps 合并为候选区域
3. **候选区域过滤**：宽高比 > 5:1 的细条 → 排除；高度 < 8px → 排除
4. 输出 MathRegion，`region_type` 一律为 MIXED（扫描版无法精确分类）

### 修改文件

- **修改** `backend/app/services/math_region_detector.py`
  - 新增 `detect_from_ocr_boxes(boxes: list[dict], page_height: int) -> List[MathRegion]`
- **修改** `backend/app/services/ocr_service.py`
  - 新增 `ocr_pages_with_boxes(page_images) -> dict[int, OcrPageResult]`
  - 旧函数 `ocr_pages()` 签名**完全不变**（防止下游破坏）
  - `OcrPageResult` dataclass：`page_index: int, text: str, boxes: list[dict] | None = None`
- **修改** `backend/tests/test_math_region_detector.py`
  - 增加聚类分支测试（mock ocr_boxes 输入）
- **修改** `miniprogram/pages/import-batch/import-batch.wxml`
  - 题目列表行：当 `parsed_content.segments` 含 `math_image` 类型时显示"含公式"角标
- **修改** `miniprogram/pages/import-batch/import-batch.js`
  - 点击角标 → 调用 `GET /import/math-preview/{id}` → 弹窗显示公式截图预览

### 验收标准

1. `ocr_pages()` 旧调用方（`import_service.py` 等）无需修改，行为不变
2. `ocr_pages_with_boxes()` 返回 `OcrPageResult`，`boxes` 字段有值
3. 扫描版 PDF 上传后，含公式题目能检测出 ≥ 1 个 MathRegion
4. 审核页题目列表"含公式"角标正确显示
5. 点击角标弹窗，可看到公式截图（至少 1 张）
6. Stage 0-4 所有验收标准继续通过

### 回归测试范围

- `tests/test_math_region_detector.py` — 聚类分支覆盖
- `tests/test_ocr_service.py` — 旧接口签名不变，不报错
- 手动回归：文字型 PDF 导入路径完整走通

---

## 阶段依赖关系

```
Stage 0 (骨架 + feature flag)
  │
  └─ Stage 1 (检测算法) → Stage 2 (截图上传) → Stage 3 (pipeline 集成)
                                                        │
                                              Stage 4 (前端渲染) ←── Stage 3 数据结构完成后可并行
                                                        │
                                                Stage 5 (扫描版升级)
```

**并行机会**：Stage 3 完成 `HybridContentBuilder` 及 §3.3 数据结构定义后，Stage 4 可用 `__mocks__/math-question-fixtures.js` 中的 mock 数据独立开发和验收。

---

## 相关链接

- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/MVP_SCOPE.md|MVP_SCOPE]] — MVP 范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录

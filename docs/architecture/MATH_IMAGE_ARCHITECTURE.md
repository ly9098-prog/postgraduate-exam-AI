# 数学公式图片化架构（冻结版 v1.2）

> **冻结版本 — 2026-05-25（第三轮修订）**
> v1.1 经 Opus Critical Auditor 第二轮审计，针对 5 个新 BLOCK 全部修订。
> 本文档为最终架构决策文件，DeepSeek 实现阶段不允许修改技术决策。
> 所有开发必须严格按照本文档执行。

---

## 0. 核心方向

**从 LaTeX 文字识别 → 数学区域截图展示**

1. 检测 PDF 页面中数学公式所在区域（bbox）
2. 截取该区域为 PNG 图片
3. 上传到本地静态文件服务（开发）/ CDN（生产）
4. 前端用 `<image>` + `binderror` 兜底渲染

---

## 1. OCR 整体 Pipeline

### 1.1 PDF 导入路径（文字型 + 扫描型）

```
POST /api/v1/import/upload (PDF)
  │
  ├─ STEP 0：【新增】读取 UploadFile 字节 → 写入临时文件（tempfile，路径传后续步骤）
  │
  ├─ STEP 1：pypdf 提取文本（保留现有切题逻辑，不动）
  │     └─ 文本字符数 < 100？
  │           ├─ YES（扫描型）→ PaddleOCR 文字识别
  │           │                  └─ 携带检测框坐标（Stage 5 扩展，见 §5.3）
  │           └─ NO（文字型） → 直接用提取文本
  │
  ├─ STEP 2：写入 QuestionImport 暂存区（每题一行，记录 page_num）
  │
  ├─ STEP 3：返回 HTTP 响应 {batch_id, count}
  │
  └─ BackgroundTask（HTTP 响应后异步执行，MATH_IMAGE_RENDER_ENABLED=true 时）：
       _run_math_pipeline(batch_id, tmp_pdf_path, db)
         ├─ fitz.open(tmp_pdf_path)         ← 临时文件此时仍存在
         ├─ MathRegionDetector.detect_document()
         ├─ FormulaImageCropper.crop_and_upload()（per-import 粒度）
         ├─ HybridContentBuilder.build()（per-import 粒度）
         ├─ 更新 QuestionImport.math_regions / parsed_content
         └─ os.unlink(tmp_pdf_path)         ← 任务末尾清理临时文件
```

> **pypdf 与 pymupdf 并存说明**：保留 pypdf 是为了不改动现有的 `_parse_pdf` 切题逻辑。pymupdf（fitz）仅用于 §2.1 字符 bbox 检测，两者处理同一文件，以 pymupdf 的页面坐标系为基准。

### 1.2 临时文件管理（NEW-BLOCK-1 修复）

```python
# import_service.import_pdf() 中的关键变化
async def import_pdf(file: UploadFile, ..., background_tasks: BackgroundTasks):
    # 1. 先把字节存到命名临时文件（delete=False，BackgroundTask 需读取）
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # 2. 用 pypdf 从 tmp_path 解析题目（现有逻辑，改为从路径读）
    records = _parse_pdf(tmp_path)

    # 3. 写 QuestionImport，每行记录 page_num
    batch_id = _save_imports(records, ...)

    # 4. 注册 BackgroundTask（传路径，不传文件句柄）
    if settings.MATH_IMAGE_RENDER_ENABLED:
        background_tasks.add_task(_run_math_pipeline, batch_id, tmp_path, db)
    else:
        os.unlink(tmp_path)  # 不需要图片化时立即清理

    return {"batch_id": batch_id, ...}
```

### 1.3 page_num 字段（NEW-BLOCK-2 修复前置）

每个 QuestionImport 行必须记录其题目所在的 PDF 页码。现有 `raw_data` JSON 中新增 `page_num: int` 字段，在 `_parse_pdf()` 切题时填入。不新增数据库列（存在 raw_data JSON 内）。

### 1.4 per-import 调度（NEW-BLOCK-2 修复）

```python
async def _run_math_pipeline(batch_id: str, tmp_pdf_path: str, db: Session):
    try:
        doc = fitz.open(tmp_pdf_path)
        imports = db.query(QuestionImport).filter_by(batch_id=batch_id).all()

        for qi in imports:
            page_num = (qi.raw_data or {}).get("page_num")
            if page_num is None:
                continue

            page = doc[page_num]
            regions = MathRegionDetector.detect_page(page)
            if not regions:
                continue

            regions = await FormulaImageCropper.crop_and_upload(
                doc, regions, get_storage(), import_id=qi.id
            )
            content = HybridContentBuilder.build(
                text=qi.parsed_content.get("text", ""), regions=regions
            )
            db.query(QuestionImport).filter_by(id=qi.id).update({
                "math_regions": [asdict(r) for r in regions],
                "parsed_content": content,
            })

        db.commit()
    except Exception as e:
        logger.warning("math pipeline 失败 batch=%s: %s", batch_id, e)
        db.rollback()
    finally:
        doc.close()
        os.unlink(tmp_pdf_path)  # 无论成败都清理
```

### 1.5 Excel / 手动导入路径（不变）

```
POST /api/v1/import/upload (Excel) 或 手动录入
  │
  └─ 完全不走 MathRegionDetector
       ├─ parsed_content 中不产生 segments 字段
       ├─ content.render_mode 保持 undefined（前端走旧路径）
       └─ 现有逻辑完全不变
```

**明确规则**：Excel 导入题永远不产生 `render_mode='segments'`，前端走 mp-html + KaTeX 旧路径。

### 1.6 Feature Flag

- 后端：`MATH_IMAGE_RENDER_ENABLED`（环境变量，默认 `false`）
- `false` 时：BackgroundTask 不注册，PDF 导入行为与修改前完全一致

---

## 2. 数学区域检测策略

### 2.1 检测方法

**主路径：Unicode 数学字符区间检测**

PyMuPDF `page.get_text("rawdict")` 逐字符遍历，以下字符视为"数学字符"：

| Unicode 区间 | 说明 |
|---|---|
| U+0391–U+03C9 | 希腊字母（Α-Ω, α-ω） |
| U+2200–U+22FF | 数学运算符（∫ ∑ ∏ ≤ ≥ ≠ ∈ ∉ ∞ ∂ …） |
| U+2100–U+214F | 字母化数字符号（ℝ ℤ ℕ ℂ …） |
| ASCII `^` `_` `{` `}` `\` | 常见 LaTeX 残留字符 |
| U+2070–U+209C | 上标/下标 Unicode |

算法：
1. 遍历页面所有 span，标记每个"数学字符"及其 bbox
2. 按行（y 坐标差 < 行高 × 0.5 视为同行）分组
3. 同行内相邻数学字符 x 间距 < 20pt → 聚合为候选区域
4. 候选区域内数学字符数 ≥ 2 → 确认为 MathRegion

**辅助路径：字体名辅助（加分项，非唯一依据）**

字体名含以下关键词时，该 span 内字符权重 +1（单字符也可触发）：
`Math`、`CMMI`、`Symbol`、`MT Extra`、`Cambria`、`STIX`、`Mathmaru`，以及含 `+Math` 后缀的子集字体

**降级路径：正则占位符**

文本中含 `$...$` / `$$...$$` 时，尝试映射回页面坐标；坐标定位失败则跳过（不报错）。

**无匹配时**：返回空列表，退化为纯文本导入，记录 `logger.info`，不中断流程。

### 2.2 截图 DPI 规则

| 区域类型 | DPI | 说明 |
|---|---|---|
| INLINE（行内） | 144 | 行高通常 16-20pt，144 DPI 足够清晰 |
| DISPLAY（独立行） | 240 | 积分、矩阵等需要更高分辨率 |
| MIXED（整行含公式） | 144 | 与文字混排，过高无益 |

### 2.3 区域扩展规则

- bbox 四周扩展 **6pt**（PDF 点坐标）
- 同一行相距 < 12pt 的相邻区域合并为一个
- 最小面积：宽 ≥ 12pt 且高 ≥ 8pt（过滤噪声点）
- Display 公式（y 范围超过行高 × 1.5）：纵向扩展至整行高度

### 2.4 区域分类

```python
class MathRegionType(str, Enum):
    INLINE = "inline"    # 行内公式（与文字混排）
    DISPLAY = "display"  # 独立行公式（如积分、矩阵）
    MIXED = "mixed"      # 整行含公式（无法分离）
```

判断规则：
- 候选区域 x 范围占整行宽度 ≥ 70% → DISPLAY
- 候选区域同行有其他文字 span → INLINE
- 其余 → MIXED

### 2.5 与 formula_normalizer.py 的关系

`formula_normalizer.py` 继续保留，**仅用于纯文本降级路径**：
- 当 `MATH_IMAGE_RENDER_ENABLED=false`，或检测返回空列表时
- 图片化路径不调用（截图取原始像素，无需文字修复）

---

## 3. 数据结构（最终版）

### 3.1 MathRegion（内存中间对象）

```python
@dataclass
class MathRegion:
    page_num: int
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1) PDF 点坐标
    region_type: MathRegionType
    raw_latex: str | None  # 文本层提取的原始公式字符串（可能为 None）
    image_url: str | None  # 截图上传后的 URL（初始 None，Stage 2 填充）
```

### 3.2 MixedSegment（题目内容片段）

```python
@dataclass
class MixedSegment:
    type: Literal["text", "math_image", "newline"]
    text: str | None      # type == "text" 时
    url: str | None       # type == "math_image" 时，必须是绝对 HTTP URL
    alt: str | None       # type == "math_image" 时，LaTeX 字符串或文字描述
    display: bool         # type == "math_image" 时，True=独立行，False=行内
```

### 3.3 Question.content（DB 字段，最终版）

```json
{
  "text": "设函数 f(x) = $\\int_0^1 x^2 dx$，求 f'(x)。",
  "segments": [
    {"type": "text",       "text": "设函数 f(x) = "},
    {"type": "math_image", "url":  "https://cdn.../202506/42_0_a1b2c3d4.png",
                           "alt":  "\\int_0^1 x^2 dx", "display": false},
    {"type": "text",       "text": "，求 f'(x)。"}
  ],
  "render_mode": "segments"
}
```

**content.text 拼接规则**（NEW-WARN-1 修复）：
- 公式位置用 `alt` 字段中的 LaTeX 字符串内联，格式 `$<alt>$`
- 示例：`"设函数 f(x) = $\\int_0^1 x^2 dx$，求 f'(x)。"`
- AI 服务（`ai_service.py`）、统计模块只读 `content.text`，不读 segments，与 AI 调用无缝兼容

**字段优先级规则**：

| 字段 | render_mode=undefined | render_mode="segments" |
|------|---|---|
| `text` | 前端渲染主体 | AI/统计用纯文本摘要（含 LaTeX） |
| `images` | 题目配图 URL 列表 | 保持不变（题目配图，非公式截图） |
| `latex` | KaTeX 公式字符串 | 废弃，不再写入 |
| `segments` | 不存在 | 前端渲染主体 |

### 3.4 question_imports 新增字段（Alembic Migration）

```sql
ALTER TABLE question_imports
  ADD COLUMN math_regions JSON DEFAULT NULL;
-- math_regions: List[MathRegion] 序列化（url 已填充）
-- 删除 v1.1 中的 formula_images 列（冗余，信息已在 segments 和 math_regions 中）
```

> `formula_images` 列已从设计中删除（NEW-WARN-2 修复）。
> 审核界面"含公式"判断改为检查 `parsed_content.segments` 是否含 `math_image` 类型。

### 3.5 questions 表（无需变更）

`content` 字段是 JSON 类型，直接存 segments 结构，无 schema 变更。

---

## 4. 前端渲染结构

### 4.1 渲染决策树

```
config.enableMathImage（miniprogram/config.js，默认 false）
  └─ true 时，再检查 content.render_mode
       ├─ "segments" → math-question 组件（新路径）
       └─ 其他      → mp-html + KaTeX（旧路径，完全不变）
```

### 4.2 新渲染组件：`math-question`

位置：`miniprogram/components/math-question/`

```xml
<!-- math-question.wxml：遍历 localSegments（内部数据，不直接改 properties） -->
<view class="math-question-wrap">
  <block wx:for="{{localSegments}}" wx:key="index">

    <text wx:if="{{item.type === 'text'}}" class="seg-text">{{item.text}}</text>

    <view wx:elif="{{item.type === 'math_image' && item.display}}" class="seg-math-display-wrap">
      <image
        wx:if="{{!item._error}}"
        src="{{item.url}}"
        mode="widthFix"
        class="seg-math-display"
        binderror="onImgError"
        data-index="{{index}}"
      />
      <text wx:else class="seg-math-fallback">{{item.alt}}</text>
    </view>

    <view wx:elif="{{item.type === 'math_image' && !item.display}}" class="seg-math-inline-wrap">
      <image
        wx:if="{{!item._error}}"
        src="{{item.url}}"
        mode="heightFix"
        class="seg-math-inline"
        binderror="onImgError"
        data-index="{{index}}"
      />
      <text wx:else class="seg-math-fallback seg-math-fallback-inline">{{item.alt}}</text>
    </view>

    <view wx:elif="{{item.type === 'newline'}}" class="seg-newline" />

  </block>
</view>
```

```javascript
// math-question.js（NEW-BLOCK-4 修复：用 observers + localSegments）
Component({
  properties: {
    segments: { type: Array, value: [] }
  },
  data: {
    localSegments: []   // 内部可写副本，properties 只读
  },
  observers: {
    // segments 变化（父组件传入新题）时重置 localSegments，_error 归零
    'segments': function(val) {
      this.setData({
        localSegments: (val || []).map(s => ({ ...s, _error: false }))
      })
    }
  },
  methods: {
    onImgError(e) {
      const index = e.currentTarget.dataset.index
      // 改 localSegments（内部 data），不改 properties
      this.setData({ [`localSegments[${index}]._error`]: true })
    }
  }
})
```

```css
/* math-question.wxss */
.seg-text {
  display: inline;
  font-size: 28rpx;
  color: #2D3E50;
  line-height: 1.8;
}
.seg-math-inline-wrap {
  display: inline-block;
  vertical-align: middle;
}
.seg-math-inline {
  height: 44rpx;
  max-width: 400rpx;
  margin: 0 4rpx;
}
.seg-math-display-wrap {
  display: block;
  text-align: center;
  margin: 16rpx 0;
}
.seg-math-display {
  max-width: 100%;
}
.seg-math-fallback {
  color: #C47A7A;
  font-size: 24rpx;
}
.seg-math-fallback-inline {
  display: inline;
}
```

> **小程序约束说明**：
> - `properties` 在基础库 2.10+ 中为只读，用 `data.localSegments` 做可写副本
> - `observers` 监听 `segments` 属性，切题时自动重置 `_error` 状态
> - `binderror` + `wx:if/_error` 切换 fallback，无 `alt` 属性
> - `lazy-load` 在非 `<scroll-view>` 中无效，不使用
> - `mode="heightFix"` 对 inline 图片保持高度恒定

### 4.3 practice.wxml 变更点

```xml
<block wx:if="{{enableMathImage && currentQuestion.content.render_mode === 'segments'}}">
  <math-question segments="{{currentQuestion.content.segments}}" />
</block>
<block wx:else>
  <mp-html class="q-content" content="{{currentQuestion._stemHtml}}" lazy-load />
</block>
```

`enableMathImage` 在 `Page.onLoad` 中从 `config.js` 读入 `this.data`，不硬编码。

---

## 5. API 定义

### 5.1 现有接口不变

所有 `/api/v1/practice/`、`/api/v1/import/` 接口不变。

### 5.2 新增接口（1 个）

#### `GET /api/v1/import/math-preview/{import_id}`

> 返回单题 segments 预览，供审核查看公式截图。需 admin token（与现有导入接口一致）。

**响应**
```json
{
  "import_id": 1,
  "has_math": true,
  "formula_count": 3,
  "segments": [...],
  "original_text": "..."
}
```

### 5.3 数学检测触发时机

```
import_upload()
  → 读 UploadFile → 写临时文件 → pypdf 切题 → 写 QuestionImport → 返回响应
  → BackgroundTask: _run_math_pipeline(batch_id, tmp_pdf_path, db)
                    → per-import 循环（见 §1.4）
                    → 任务末尾 os.unlink(tmp_pdf_path)
```

### 5.4 扫描版 OCR 返回结构兼容（NEW-BLOCK-5 修复，Stage 5 适用）

```python
# ocr_service.py 中新方法（不改旧方法签名）
@dataclass
class OcrPageResult:
    page_index: int
    text: str
    boxes: list[dict] | None = None  # [{"bbox": [x0,y0,x1,y1], "conf": 0.9}]

def ocr_pages_with_boxes(page_images) -> dict[int, OcrPageResult]:
    """新方法，返回含 boxes 的结果。原 ocr_pages() 保留不变。"""
    ...
```

旧 `ocr_pages() -> dict[int, str]` 签名**完全保留**，Stage 5 新增 `ocr_pages_with_boxes()` 独立方法，下游解构不受影响。

---

## 6. DB Schema 变更汇总

| 表 | 变更类型 | 字段 | 说明 |
|----|----------|------|------|
| `question_imports` | ADD COLUMN | `math_regions` JSON | MathRegion 列表序列化（url 已填充） |
| `questions` | 无变更 | `content` JSON | segments 结构直接存入现有字段 |

---

## 7. 兼容旧数据策略

### 7.1 原则

- **不迁移旧数据**：现有题目继续用旧渲染路径
- **双路径 + 双开关**：`enableMathImage`（前端）+ `render_mode`（数据）
- **渐进替换**：仅新导入题目采用 segments 结构

### 7.2 回滚机制

| 回滚场景 | 操作 |
|----------|------|
| 后端回滚（停止产出新 segments） | 设 `MATH_IMAGE_RENDER_ENABLED=false` 并重启 |
| 前端回滚（回退旧渲染） | 设 `config.enableMathImage = false` 并发版 |
| 紧急全量回滚 | 双开关均关闭，所有题目走旧路径 |
| DB 回滚 | Alembic `downgrade`（删 `math_regions` 列，`questions.content` 不变） |

### 7.3 存储后端切换警告

生产环境切换存储后端（COS → OSS）时，`questions.content.segments[i].url` 中已有的绝对 URL 将失效。需提前准备数据迁移脚本批量替换 URL 前缀。

---

## 8. 对象存储接入

**禁止 base64 data URI 进入数据库。**

| 环境 | 实现 | URL 形式 |
|------|------|----------|
| 开发 | `LocalFileStorage`：保存到 `backend/static/formulas/`，FastAPI StaticFiles 服务 | `{PUBLIC_BASE_URL}/static/formulas/{YYYYMM}/{filename}.png` |
| 生产 | `COSStorage` / `OSSStorage`（占位实现，后填凭证） | `https://{bucket}.{region}.myqcloud.com/{YYYYMM}/{filename}.png` |

**`PUBLIC_BASE_URL` 配置**（NEW-BLOCK-3 修复）：
- 环境变量 `PUBLIC_BASE_URL`，默认 `http://localhost:8000`
- 开发真机调试时改为局域网 IP：`http://192.168.x.x:8000`
- 生产时为 CDN 根域名
- `LocalFileStorage.upload()` 返回 `f"{settings.PUBLIC_BASE_URL}/static/formulas/{YYYYMM}/{filename}.png"`

**URL 命名规范**（NEW-WARN-8 修复，去掉重复前缀）：
- 文件保存路径：`backend/static/formulas/{YYYYMM}/{import_id}_{page}_{content_hash}.png`
- URL：`{PUBLIC_BASE_URL}/static/formulas/{YYYYMM}/{import_id}_{page}_{content_hash}.png`
- `content_hash` = `md5(png_bytes)[:8]`（内容哈希，相同公式图片可去重）（NEW-WARN-3 修复）

**StorageBackend 接口**：
```python
class StorageBackend(ABC):
    @abstractmethod
    async def upload(self, filename: str, data: bytes) -> str:
        """上传图片，返回绝对 HTTP URL"""
```

**运维要求**：生产 CDN 域名需在微信公众平台"downloadFile 合法域名"中配置，否则真机无法加载图片。

---

## 9. 约束与边界

| 约束 | 说明 |
|------|------|
| 禁止 LaTeX OCR 优化 | 不做 pix2tex / Mathpix 接入 |
| 图片优先 | 凡能截图展示的公式，优先截图而非文字 |
| 兼容旧 MVP | 现有刷题系统零改动，双路径 + 双开关保护 |
| 人工审核不跳过 | 所有含公式截图的题目仍须人工确认 |
| 降级保证 | 公式检测失败时退化为纯文本，不阻断流程，不报 500 |
| 无本地模型 | 不部署专项公式模型，只用 fitz 字符分析 |
| 禁止 base64 进 DB | 开发环境也用本地静态文件 URL |
| Excel 路径不变 | Excel 导入不产生 segments，不走图片化路径 |
| 存储切换需迁移脚本 | 切换 CDN/云存储时需批量替换 URL（TODO） |

---

## 10. 测试集与召回率基线

| 编号 | PDF 来源 | 预期公式数 | 类型 |
|------|----------|-----------|------|
| T01 | 自制：LaTeX 编译，含积分/极限/矩阵 10-15 个公式，3-5 页 | ≥ 10 | 文字型，非版权题 |
| T02 | 自制：Word + MathType 导出，含混合字体公式 | ≥ 10 | 文字型，非版权题 |
| T03 | 自制：408 风格 ASCII 表达式（f(x)=x^2 等） | ≥ 10 | 文字型，纯 ASCII 公式 |
| T04 | 自制或实际扫描版（可选，Stage 5 使用） | ≥ 10 | 扫描型 |

> **版权说明**（NEW-WARN-7 修复）：测试 PDF 必须是开发者自行用 LaTeX/Word 生成的代表性文件，禁止将考研真题 PDF 直接提交到 git 仓库。

**验收阈值**：

| 指标 | 要求 |
|------|------|
| T01 召回率 | ≥ 60% |
| T02 召回率 | ≥ 50%（MathType 字体名不稳定） |
| T03 误检率 | ≤ 10% |
| 无公式页面误检 | = 0 |
| 任意测试文件处理不抛异常 | 100% |

---

## 11. 实现注意事项（踩坑笔记）

> 本节为实现阶段快速参考，遇到对应问题先查这里。

### 11.1 PDF 临时文件（对应 §1.2）

- `UploadFile.file` 是 `SpooledTemporaryFile`，HTTP 响应发出后句柄即失效
- **必须**先 `await file.read()` 写入 `NamedTemporaryFile(delete=False)`
- BackgroundTask 持有路径字符串，`finally` 块做 `os.unlink`
- 异常时也要 unlink，否则磁盘泄漏

### 11.2 URL 配置（对应 §8）

- 开发真机调试：`PUBLIC_BASE_URL=http://192.168.x.x:8000`（改 `.env`）
- 真机还需在小程序 `app.json` 的 `permission` 下或使用开发者工具"不校验域名"
- 生产上线前必须配置微信公众平台 downloadFile 合法域名

### 11.3 小程序 observers（对应 §4.2）

- 小程序基础库 2.6.1+ 支持 observers
- `segments` 从父传入时 observers 触发，重置所有 `_error: false`
- `onImgError` 只改 `localSegments[i]._error`，不改 `properties.segments`
- 切换到下一题时父组件重新赋值 `segments`，observers 自动重置，无需手动清理

### 11.4 pymupdf 字符坐标系（对应 §1.1）

- pymupdf bbox 单位是 PDF 点（1pt = 1/72 英寸），不是像素
- `page.get_pixmap(dpi=144)` 时，像素坐标 = PDF 坐标 × 144/72 = PDF 坐标 × 2
- crop 时用 `fitz.Rect(bbox)` 直接传点坐标，pymupdf 内部换算

### 11.5 per-import 循环与 page_num（对应 §1.3/§1.4）

- `_parse_pdf()` 现有逻辑按题号 regex 切题，未记录 page_num
- 实现时需在切题循环内追踪当前页码，存入 `raw_data["page_num"]`
- 一题跨多页时，取题目首行所在页（边界情况，人工审核时可修正）

### 11.6 OCR 返回结构兼容（对应 §5.4）

- `ocr_pages()` 旧函数**绝对不改签名**
- Stage 5 新增独立函数 `ocr_pages_with_boxes()`
- 两函数可共用内部逻辑，用参数区分是否返回 boxes

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则

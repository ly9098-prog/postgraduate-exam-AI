> **不要按本文施工（2026-09-23）。** 这是收进 `backlog/` 的历史任务书，不代表当前工作。现行范围见 `docs/project/ROADMAP.md`。

你现在需要在一个现有 OCR Pipeline 工程中进行一次“最小侵入式扩展”，新增一个 PaddleOCR-VL Adapter，并将其接入系统的 AI OCR 模型配置体系，同时支持在 admin 前端 ai-settings 页面中配置和切换使用 PaddleOCR-VL-1.6 模型。

========================
🎯 一、目标
========================

1. 新增 PaddleOCR-VL Adapter（封装外部 OCR API）
2. 将其接入现有 OCR Model Router（与 Qwen-VL / DeepSeek 并列）
3. 支持在 admin 前端 ai-settings 页面选择：
   - PaddleOCR-VL-1.6
   - PaddleOCR-VL-其他版本（预留扩展）
4. 不破坏现有 pipeline / OCRFixRouter / Qwen-VL / DeepSeek 流程
5. 保持 backward compatibility（默认不影响现有行为）

========================
🧠 二、外部 API（必须封装）
========================

OCR API：

POST https://paddleocr.aistudio-app.com/api/v2/ocr/jobs

Header:
Authorization: bearer <TOKEN>
Content-Type: multipart/form-data or application/json

Model:
PaddleOCR-VL-1.6

两种模式：
1. URL模式：
   {
     "fileUrl": "...",
     "model": "PaddleOCR-VL-1.6",
     "optionalPayload": {...}
   }

2. 本地文件：
   multipart upload + form-data

Polling:
GET /api/v2/ocr/jobs/{jobId}

状态：
- pending
- running
- done
- failed

最终结果：
resultUrl.jsonUrl (JSONL)

========================
🏗️ 三、架构设计要求
========================

请实现一个新的模块：

/ocr_vl/
    paddleocr_vl_adapter.py
    paddleocr_vl_client.py
    paddleocr_vl_router_hook.py (optional)

要求：

### 1. Adapter 设计
必须实现统一接口：

class OCRVLFixer:
    def run(self, file_path: str, file_url: str = None) -> OCRResult

输出结构必须对齐现有 OCR pipeline：

OCRResult:
- text: str
- boxes: list
- confidence: float
- raw: dict

========================
🔁 四、接入 OCR Router（关键）
========================

必须在现有 OCR 体系中新增一个 model option：

MODEL_REGISTRY 增加：

"paddleocr-vl-1.6": PaddleOCRVLAdapter

并接入现有逻辑：

ocr_fix/router.py 或 ocr_service.py

优先级建议：

if model == "qwen":
    use Qwen-VL
elif model == "paddleocr-vl-1.6":
    use PaddleOCR-VL
elif model == "deepseek":
    fallback logic

========================
⚙️ 五、Admin 前端（ai-settings）
========================

必须新增一个配置项：

字段：
ocr_model_provider

支持值：
- qwen-vl
- deepseek
- paddleocr-vl-1.6  ⭐新增

UI要求：

1. 下拉选择 OCR Provider
2. Tooltip：
   “PaddleOCR-VL is a high-accuracy OCR engine with document understanding”
3. 默认值保持原系统不变（不能影响生产）

后端：

ai-settings API 必须支持：

GET /admin/ai-settings
POST /admin/ai-settings

新增字段：

{
  "ocr_model_provider": "paddleocr-vl-1.6"
}

========================
🔌 六、配置系统接入
========================

必须接入：

config/model_config_resolver.py

新增 mapping：

paddleocr-vl-1.6 → PaddleOCRVLAdapter

支持：

- env override
- admin override
- fallback to qwen-vl

========================
🧪 七、稳定性要求
========================

必须满足：

1. 不影响现有 pipeline_orchestrator
2. 不影响 OCRFixRouter（Qwen/DeepSeek）
3. 失败自动 fallback：
   PaddleOCR-VL failed → PaddleOCR local → Qwen-VL
4. 必须有 timeout + retry（至少 3 次）

========================
📦 八、输出 JSON 格式统一
========================

必须标准化输出：

{
  "text": "...",
  "boxes": [[x1,y1,x2,y2]],
  "confidence": 0.0-1.0,
  "source": "paddleocr-vl-1.6"
}

========================
🧯 九、错误处理
========================

必须实现：

- job submit failed
- polling timeout
- jsonUrl missing
- malformed JSONL
- image upload failure

全部必须 fallback，不得 crash pipeline

========================
⚡ 十、非功能要求
========================

- 不允许修改 OCRFixRouter 核心逻辑（只扩展）
- 不允许改动 question_splitter / ai_repair
- 新模块必须可独立运行测试
- 必须提供 demo script：

python backend/scripts/demo_paddleocr_vl.py

========================
📌 十一、验收标准
========================

✔ 可以在 ai-settings 切换 OCR 模型
✔ PaddleOCR-VL 可以单独运行
✔ pipeline 自动识别新 adapter
✔ fallback 正常
✔ 不影响现有 Qwen / DeepSeek 路径
✔ OCR 输出格式一致

========================
🚀 最终目标
========================

实现一个“可插拔 OCR 模型体系”：

Qwen-VL (视觉纠错)
DeepSeek (文本修复)
PaddleOCR-VL (外部高精 OCR API)

三者统一通过 router 管理
admin 可动态切换
pipeline 无感知扩展
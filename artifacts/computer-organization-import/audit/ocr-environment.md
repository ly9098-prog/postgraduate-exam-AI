# OCR 环境与工具状态（cs_ds 导入）

| 工具 | 状态 | 说明 |
|------|------|------|
| 后端远程 OCR `http://172.27.64.1:8080/ocr` | ✅ 可用 | PaddleX HTTP backend（PaddleOCR-VL），.env `OCR_EXECUTION_BACKEND=paddlex_http`。返回 `ocrResults[].prunedResult.{rec_texts,rec_scores,rec_polys,dt_polys}`。Pipeline 主 OCR 引擎。 |
| OCR MCP `PP-OCRv6`（aistudio） | ❌ 401 | `paddleocr_mcp`（uvx，`PADDLEOCR_MCP_PPOCR_SOURCE=aistudio`，token `89f6ef…`）。直连 `POST https://paddleocr.aistudio-app.com/api/v2/ocr/jobs` 返回 `401 Unauthorized` — token 失效/过期。MCP 工具返回 `Error calling tool 'ocr'`。**未虚构 MCP 结果**。 |
| 本地 PP-OCRv4 `backend/.venv` paddleocr 2.7.3 | ✅ 可用（CPU） | 独立第二引擎，用于交叉核验。init ~5s，page-0001 识别正常（conf 0.995–1.0）。规避 WSL GPU 易碎：强制 CPU + 每次独立子进程。 |
| Claude 视觉读图（Read 工具读 PNG） | ✅ 可用 | 原始页面视觉证据为最高依据。 |

**结论**：aistudio MCP 因凭据失效不可用。按要求不得伪造 MCP 结果，故独立核验改用本地 PP-OCRv4（同 PaddleOCR 家族但不同实例/版本，相对 8080 后端独立），并辅以 Claude 直接读图复核。报告中 mcp_ocr_confidence 以本地独立引擎为准并在报告中如实说明。

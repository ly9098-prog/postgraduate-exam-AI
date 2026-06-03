## P0 书籍扫描版PDF文件文件导入解析超时

问题：
导入"/backend/tests/fixtures/wangdao_408.pdf"全文扫描解析时，等待1个小时仍然没有解析完成，文件状态始终不变

前端控制台打印：

```
[TRACE:NO_TRACE][API_ERROR] ➤ {method: "GET", url: "/import/pipelines/pl_20260603_185753_ea16b3", message: "request:fail timeout"} ➤ 查询导入状态失败 ➤ {errMsg: "request:fail timeout"} (env: Windows,mp,2.01.2510290; lib: 3.6.6)
```

后端控制台打印：

```
2026-06-03 18:57:53,225 INFO sqlalchemy.engine.Engine [cached since 281s ago] (72,)
2026-06-03 18:57:53 | INFO    | sqlalchemy.engine.Engine | [cached since 281s ago] (72,)
2026-06-03 18:57:53,402 INFO sqlalchemy.engine.Engine ROLLBACK
2026-06-03 18:57:53 | INFO    | sqlalchemy.engine.Engine | ROLLBACK
2026-06-03 18:57:53 | INFO    | 2240ai | POST /api/v1/import/pipeline/upload → 200 (2222ms)
2026-06-03 18:57:53 | INFO    | uvicorn.access | 127.0.0.1:54632 - "POST /api/v1/import/pipeline/upload HTTP/1.1" 200
2026-06-03 18:57:53 | INFO    | app.features.pipeline_orchestrator | PDF text only 0 chars, attempting PaddleOCR fallback
/home/lmh/projects/postgraduate-ai/backend/.venv/lib/python3.12/site-packages/paddle/utils/cpp_extension/extension_utils.py:712: UserWarning: No ccache found. Please be aware that recompiling all source files may be required. You can download and install ccache from: https://github.com/ccache/ccache/blob/master/doc/INSTALL.md
  warnings.warn(warning_message)
```


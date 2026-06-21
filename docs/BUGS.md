# BUGS

##### 生产环境后端使用批量图片导入题目报错

```python

2026-06-21 02:14:48 | ERROR   | app.features.batch_image_import_service | batch image item failed: item_id=1 file=faulty_case_1.png
Traceback (most recent call last):
  File "/app/app/services/ocr_service.py", line 56, in _get_ocr
    from paddleocr import PaddleOCR  # 延迟导入，不影响未开启 OCR 的启动速度
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/app/.local/lib/python3.11/site-packages/paddleocr/__init__.py", line 15, in <module>
    from paddlex.inference.utils.benchmark import benchmark
ModuleNotFoundError: No module named 'paddlex'

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/app/app/features/batch_image_import_service.py", line 313, in _process_source
    result = await _run_single_image(item_id, src.source_file, content, subject, options)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/app/features/batch_image_import_service.py", line 247, in _run_single_image
    raw_ocr_text = await asyncio.to_thread(ocr_image, content)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/asyncio/threads.py", line 25, in to_thread
    return await loop.run_in_executor(None, func_call)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/concurrent/futures/thread.py", line 58, in run
    result = self.fn(*self.args, **self.kwargs)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/app/services/ocr_service.py", line 511, in ocr_image
    _, text = _ocr_one_page(image_bytes, 1)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/app/services/ocr_service.py", line 445, in _ocr_one_page
    ocr = _get_ocr()
          ^^^^^^^^^^
  File "/app/app/services/ocr_service.py", line 58, in _get_ocr
    raise RuntimeError(_OCR_DEPENDENCY_ERROR) from exc
RuntimeError: OCR 依赖未安装：paddleocr，请先安装 requirements-ocr.txt

```


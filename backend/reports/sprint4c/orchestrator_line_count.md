# Orchestrator Line Count

Generated: 2026-07-18T11:06:47.018114

## Before

| Metric | Value |
|--------|-------|
| File | `app/features/pipeline_orchestrator.py` |
| Total lines | 6409 |
| Code lines | 5220 |

## Responsibilities Found

| Responsibility | Call Sites |
|---------------|------------|
| ai_repair | 1 |
| document_ir_construction | 7 |
| page_rendering | 2 |
| persistence | 6 |
| question_splitting | 1 |
| review_artifact | 1 |
| storage_delete | 2 |

## Details

### ai_repair
- Line 4539: `run_repair_stage`

### document_ir_construction
- Line 334: `get_document_ir`
- Line 339: `_blocks_to_document_ir`
- Line 1295: `_blocks_to_document_ir`
- Line 537: `_get_blocks_document_ir`
- Line 1471: `document_ir_to_dict`
  ... (7 total)

### page_rendering
- Line 4957: `pdf_renderer.render_pages`
- Line 5011: `pdf_renderer.cleanup`

### persistence
- Line 2433: `_save_artifact`
- Line 2441: `_save_artifact`
- Line 2448: `_save_artifact`
- Line 2452: `_save_artifact`
- Line 2456: `_save_artifact`
  ... (6 total)

### question_splitting
- Line 4053: `split_questions`

### review_artifact
- Line 4836: `run_review_stage`

### storage_delete
- Line 4710: `get_storage`
- Line 4808: `storage.upload`

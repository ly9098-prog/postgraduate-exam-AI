"""Debug: check normalized blocks entering the question splitter."""
import asyncio
import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['OCR_ENABLED'] = 'true'
os.environ['OCR_USE_GPU'] = 'false'
os.environ['OCR_MAX_WORKERS'] = '1'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logging.basicConfig(level=logging.WARNING, format='%(levelname)s:%(name)s:%(message)s')

from app.core.database import init_db
from app.features.pipeline_orchestrator import ImportPipeline
from app.features.question_splitter import split_questions, _find_question_boundaries


async def main():
    await init_db()

    pdf_path = '/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf'
    with open(pdf_path, 'rb') as f:
        content = f.read()

    # Use the pipeline to run extract stage only
    from app.features.pipeline_orchestrator import _extract_text_blocks
    from app.features.pipeline_stages.structure_freeze_stage import run_structure_freeze_stage
    from app.features.import_mode import detect_import_mode, ImportMode

    # Extract text blocks from PDF (handles OCR fallback)
    raw_blocks = _extract_pdf_blocks(tmp_path, page_start=1, page_end=10)

    # Check if scanned - need OCR
    total_text = sum(len(b.get("text", "")) for b in raw_blocks)
    print(f'Extracted {len(raw_blocks)} raw text blocks, total chars: {total_text}')

    if total_text < 100:
        from app.features.pipeline_orchestrator import _ocr_scanned_pdf
        ocr_blocks = _ocr_scanned_pdf(tmp_path, page_start=1, page_end=10)
        if ocr_blocks:
            raw_blocks = ocr_blocks

    print(f'Final blocks: {len(raw_blocks)}')
    for b in raw_blocks:
        print(f'  Page {b["page"]}: "{b.get("text","")[:100]}"')

        # Build full text like splitter does
        parts = []
        for b in nblocks:
            parts.append(b.get('normalized_text', ''))
        full_text = '\n'.join(parts)
        print(f'\nFull text ({len(full_text)} chars):')
        print(full_text)

        # Find boundaries
        boundaries = _find_question_boundaries(full_text)
        print(f'\nBoundaries found: {len(boundaries)}')
        for num, pos in boundaries:
            line_start = full_text.rfind('\n', 0, pos) + 1 if pos > 0 else 0
            line_end = full_text.find('\n', pos)
            line = full_text[line_start:line_end] if line_end > 0 else full_text[line_start:line_start + 80]
            print(f'  Q{num} at pos {pos}: "{line.strip()[:80]}"')

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == '__main__':
    asyncio.run(main())

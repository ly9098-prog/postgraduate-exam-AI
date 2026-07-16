"""Reliable OCR → TXT → Pipeline import for scanned PDF.

Strategy: PaddleOCR text-only OCR (works reliably) per page → save TXT →
import through standard pipeline stages (normalize, split, validate, review).
"""
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['OCR_ENABLED'] = 'true'
os.environ['OCR_USE_GPU'] = 'false'
os.environ['OCR_MAX_WORKERS'] = '1'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('ocr-to-txt')

from app.core.database import init_db


def ocr_pdf_to_text(pdf_path: str, page_start: int, page_end: int, dpi: int = 150) -> str:
    """OCR PDF pages to text using PaddleOCR (text-only, one page at a time).

    Each page is OCR'd independently with fresh preprocessing.
    Returns concatenated text with page markers.
    """
    import fitz
    import numpy as np
    from PIL import Image
    import io

    # Initialize PaddleOCR once (text-only OCR is reliable)
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=False, show_log=False,
                    use_mkldnn=False, cpu_threads=1)

    doc = fitz.open(pdf_path)
    total_pages = min(page_end, len(doc))
    texts = []

    for i in range(page_start - 1, total_pages):
        page = doc[i]
        # Render at 150 DPI (reliable resolution)
        pix = page.get_pixmap(dpi=dpi)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)

        try:
            result = ocr.ocr(img_array, cls=True)
            if result and result[0]:
                lines = []
                for line in result[0]:
                    text = line[1][0]
                    if text.strip():
                        lines.append(text.strip())
                page_text = '\n'.join(lines)
                texts.append(page_text)
                logger.info(f'  Page {i+1}: {len(lines)} lines, {len(page_text)} chars')
            else:
                logger.warning(f'  Page {i+1}: No text detected')
                texts.append('')
        except Exception as e:
            logger.warning(f'  Page {i+1}: OCR failed: {e}')
            texts.append('')

        pix = None  # release memory

    doc.close()
    return '\n\n'.join(texts)


async def import_via_pipeline(text_content: str, batch_name: str):
    """Import text through the standard pipeline."""
    from app.features.pipeline_orchestrator import run_import_pipeline
    import tempfile

    fd, tmp_path = tempfile.mkstemp(prefix=f'ocr_txt_{batch_name}_', suffix='.txt')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text_content)

        pipeline_id = f'ocr_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{batch_name}'
        options = {
            'enable_ai_repair': True,
            'confidence_threshold': 0.6,
            'import_mode': 'auto',
        }

        logger.info(f'Importing TXT pipeline {pipeline_id}...')
        async with async_session() as db:
            result = await run_import_pipeline(
                file_path=tmp_path,
                source_type='txt',
                source_file=f'ds_sc_{batch_name}.txt',
                subject_id=9,
                options=options,
                db=db,
                pipeline_id=pipeline_id,
            )

        count = result.get('stats', {}).get('to_review', 0)
        status = result.get('status', 'unknown')
        logger.info(f'  Pipeline {pipeline_id}: {count} questions, status={status}')
        return pipeline_id, count, status, result
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def main():
    await init_db()

    pdf_path = '/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf'

    # Process in chunks to manage memory and allow verification
    chunk_size = 50
    total_pages = 500
    start_page = 1  # Full import: ALL pages

    artifact_dir = '/home/lmh/projects/postgraduate-ai/artifacts/wangdao-os/ocr-txt-import'
    os.makedirs(artifact_dir, exist_ok=True)

    total_questions = 0
    all_results = []
    pipeline_ids = []

    for chunk_start in range(start_page, total_pages + 1, chunk_size):
        chunk_end = min(chunk_start + chunk_size - 1, total_pages)
        chunk_name = f'p{chunk_start:03d}-{chunk_end:03d}'

        logger.info(f'\n{"="*60}')
        logger.info(f'Chunk {chunk_name}: OCR pages {chunk_start}-{chunk_end}')
        logger.info(f'{"="*60}')

        # Step 1: OCR pages to text
        logger.info('OCR phase...')
        start = time.monotonic()
        text = ocr_pdf_to_text(pdf_path, chunk_start, chunk_end)
        ocr_elapsed = time.monotonic() - start
        logger.info(f'OCR done: {ocr_elapsed:.0f}s, {len(text)} chars')

        # Save OCR text
        txt_path = f'{artifact_dir}/ocr_text_{chunk_name}.txt'
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(text)

        # Step 2: Import through pipeline
        logger.info('Pipeline import phase...')
        start = time.monotonic()
        pipeline_id, count, status, result = await import_via_pipeline(text, chunk_name)
        pipeline_elapsed = time.monotonic() - start
        logger.info(f'Pipeline done: {pipeline_elapsed:.0f}s, {count} questions, status={status}')

        total_questions += count
        pipeline_ids.append(pipeline_id)
        all_results.append({
            'chunk': chunk_name,
            'pages': f'{chunk_start}-{chunk_end}',
            'pipeline_id': pipeline_id,
            'text_length': len(text),
            'ocr_sec': ocr_elapsed,
            'pipeline_sec': pipeline_elapsed,
            'question_count': count,
            'status': status,
        })

        # Save per-chunk result
        with open(f'{artifact_dir}/result_{chunk_name}.json', 'w') as f:
            json.dump({
                'pipeline_id': pipeline_id,
                'pages': f'{chunk_start}-{chunk_end}',
                'result': {k: v for k, v in result.items() if k != 'diagnostics'},
            }, f, ensure_ascii=False, indent=2, default=str)

    # Summary
    print('\n' + '='*60)
    print('IMPORT COMPLETE')
    print('='*60)
    print(f'Total pages: {total_pages}')
    print(f'Total chunks: {len(all_results)}')
    print(f'Total questions imported: {total_questions}')

    for r in all_results:
        print(f'  {r["chunk"]}: {r["question_count"]} questions ({r["status"]})')

    # Save summary
    summary = {
        'pdf_path': pdf_path,
        'total_pages': total_pages,
        'start_page': start_page,
        'chunk_size': chunk_size,
        'chunks': all_results,
        'total_questions': total_questions,
        'pipeline_ids': pipeline_ids,
        'completed_at': datetime.now().isoformat(),
    }
    with open(f'{artifact_dir}/summary.json', 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # DB stats
    import sqlite3
    db = sqlite3.connect('postgraduate.db')
    cur = db.cursor()
    qi = cur.execute('SELECT COUNT(*) FROM question_imports').fetchone()[0]
    print(f'\nTotal question_imports in DB: {qi}')
    db.close()


if __name__ == '__main__':
    asyncio.run(main())

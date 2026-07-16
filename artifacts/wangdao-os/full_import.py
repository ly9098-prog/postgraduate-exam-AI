"""Full import: PDF pages 11-500 through the existing pipeline.
This runs in batches to ensure reliable processing with proper checkpointing.
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['OCR_ENABLED'] = 'true'
os.environ['OCR_USE_GPU'] = 'false'
os.environ['OCR_MAX_WORKERS'] = '1'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logger = logging.getLogger('full-import')
logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.WARNING)

from app.core.database import init_db, async_session

CHUNK_SIZE = 50  # Process 50 pages per batch


async def import_batch(page_start, page_end, batch_index, total_batches):
    """Import a single page range."""
    import tempfile, os
    from app.features.pipeline_orchestrator import run_import_pipeline

    pdf_path = '/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf'
    fd, tmp_path = tempfile.mkstemp(prefix=f'import_batch{batch_index}_', suffix='.pdf')
    try:
        with os.fdopen(fd, 'wb') as f:
            with open(pdf_path, 'rb') as src:
                f.write(src.read())

        pipeline_id = f'full_{datetime.now().strftime("%Y%m%d_%H%M%S")}_b{batch_index}'
        options = {
            'enable_ai_repair': True,
            'confidence_threshold': 0.6,
            'import_mode': 'auto',
            'page_start': page_start,
            'page_end': page_end,
        }

        logger.info(f'Batch {batch_index}/{total_batches}: pages {page_start}-{page_end}')
        start = time.monotonic()

        async with async_session() as db:
            result = await run_import_pipeline(
                file_path=tmp_path,
                source_type='pdf',
                source_file='ds_sc.pdf',
                subject_id=9,
                options=options,
                db=db,
                pipeline_id=pipeline_id,
            )

        elapsed = time.monotonic() - start
        count = result.get('stats', {}).get('to_review', 0)
        status = result.get('status', 'unknown')
        errors = result.get('errors', [])

        logger.info(f'  Batch {batch_index}: {elapsed:.0f}s, {count} questions, status={status}')
        if errors:
            logger.warning(f'  Errors: {errors}')

        # Save per-batch result
        batch_dir = '/home/lmh/projects/postgraduate-ai/artifacts/wangdao-os/full-import'
        os.makedirs(batch_dir, exist_ok=True)
        with open(f'{batch_dir}/batch_{batch_index:03d}_p{page_start}-{page_end}.json', 'w') as f:
            json.dump({
                'batch_index': batch_index,
                'page_start': page_start,
                'page_end': page_end,
                'pipeline_id': pipeline_id,
                'elapsed_sec': elapsed,
                'result': {k: v for k, v in result.items() if k != 'diagnostics'},
            }, f, ensure_ascii=False, indent=2, default=str)

        return count, status, errors

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def main():
    await init_db()

    total_pages = 500
    batches = []
    for start in range(11, total_pages + 1, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE - 1, total_pages)
        batches.append((start, end))

    total_batches = len(batches)
    logger.info(f'Full import: {total_pages - 10} pages in {total_batches} batches of up to {CHUNK_SIZE} pages')

    total_questions = 0
    failed_batches = []

    for idx, (start, end) in enumerate(batches, 1):
        try:
            count, status, errors = await import_batch(start, end, idx, total_batches)
            total_questions += count
            if status != 'completed':
                failed_batches.append({
                    'batch': idx,
                    'pages': f'{start}-{end}',
                    'status': status,
                    'errors': errors,
                })
        except Exception as e:
            logger.error(f'Batch {idx} CRASHED: {e}')
            failed_batches.append({
                'batch': idx,
                'pages': f'{start}-{end}',
                'status': 'crashed',
                'errors': [str(e)],
            })

        if failed_batches:
            logger.warning(f'Batch {idx} failed. Continuing with next batch...')

    # Summary
    print('\n' + '='*60)
    print('FULL IMPORT COMPLETE')
    print('='*60)
    print(f'Total batches: {total_batches}')
    print(f'Failed batches: {len(failed_batches)}')
    print(f'Total questions imported: {total_questions}')

    if failed_batches:
        print(f'\nFailed batches:')
        for fb in failed_batches:
            print(f'  Batch {fb["batch"]} (pages {fb["pages"]}): {fb["status"]}')
            for e in fb.get('errors', []):
                print(f'    Error: {e}')

    # Check DB
    import sqlite3
    db = sqlite3.connect('postgraduate.db')
    cur = db.cursor()
    qi_total = cur.execute('SELECT COUNT(*) FROM question_imports').fetchone()[0]
    print(f'\nTotal question_imports: {qi_total}')
    db.close()

    # Save summary
    summary = {
        'total_batches': total_batches,
        'failed_batches': failed_batches,
        'total_questions': total_questions,
        'total_question_imports': qi_total,
        'completed_at': datetime.now().isoformat(),
    }
    with open('/home/lmh/projects/postgraduate-ai/artifacts/wangdao-os/full-import/summary.json', 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f'Summary saved to artifacts/wangdao-os/full-import/summary.json')


if __name__ == '__main__':
    asyncio.run(main())

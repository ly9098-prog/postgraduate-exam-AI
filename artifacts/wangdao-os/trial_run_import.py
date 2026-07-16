"""Trial import: directly run pipeline on PDF pages 1-10.

This calls run_import_pipeline() directly (no task queue needed).
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
os.environ['OCR_USE_GPU'] = 'true'
os.environ['REDIS_URL'] = ''
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('trial-import')

from app.core.database import init_db, async_session


async def main():
    logger.info('Initializing database...')
    await init_db()

    pdf_path = '/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf'

    # Save to temp file for pipeline (needs file path for fitz mmap)
    fd, tmp_path = tempfile.mkstemp(prefix='trial_import_', suffix='.pdf')
    try:
        with os.fdopen(fd, 'wb') as f:
            with open(pdf_path, 'rb') as src:
                f.write(src.read())
        logger.info(f'Temporary PDF saved to {tmp_path}')

        from app.features.pipeline_orchestrator import run_import_pipeline

        pipeline_id = f'trial_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        options = {
            'enable_ai_repair': True,
            'confidence_threshold': 0.6,
            'import_mode': 'auto',
            'page_start': 1,
            'page_end': 10,
        }

        logger.info(f'Starting pipeline {pipeline_id} for pages 1-10...')
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
        logger.info(f'Pipeline completed in {elapsed:.1f}s')

        # Save result
        out_dir = '/home/lmh/projects/postgraduate-ai/artifacts/wangdao-os/trial-run'
        with open(f'{out_dir}/pipeline_result.json', 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        print('\n=== PIPELINE RESULT ===')
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        # Check DB
        print('\n=== Question Imports in DB ===')
        async with async_session() as db:
            from app.models.question_import import QuestionImport
            from sqlalchemy import select, func
            total = (await db.execute(select(func.count(QuestionImport.id)))).scalar()
            print(f'Total question_imports: {total}')

            rows = (await db.execute(
                select(QuestionImport).order_by(QuestionImport.source_order_index)
            )).scalars().all()
            for r in rows:
                print(f'  ID={r.id} batch={r.batch_id} status={r.status} '
                      f'page={r.source_page_start} '
                      f'qno={r.source_question_no} '
                      f'type={r.question_type} '
                      f'answer_status={r.answer_status}')

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
            logger.info(f'Cleaned up temp file {tmp_path}')

    print('\nDone!')


if __name__ == '__main__':
    asyncio.run(main())

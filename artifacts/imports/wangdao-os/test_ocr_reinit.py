"""Test OCR reinit fix with pages 11-30 (previously failing pages)."""
import asyncio, json, logging, os, sys, tempfile, time
from datetime import datetime

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['OCR_ENABLED'] = 'true'
os.environ['OCR_USE_GPU'] = 'false'
os.environ['OCR_MAX_WORKERS'] = '1'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ocr-reinit-test')

from app.core.database import init_db, async_session


async def main():
    await init_db()

    pdf_path = '/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf'
    fd, tmp_path = tempfile.mkstemp(prefix='ocr_reinit_test_', suffix='.pdf')
    try:
        with os.fdopen(fd, 'wb') as f:
            with open(pdf_path, 'rb') as src:
                f.write(src.read())

        from app.features.pipeline_orchestrator import run_import_pipeline

        pipeline_id = f'reinit_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        options = {
            'enable_ai_repair': True,
            'confidence_threshold': 0.6,
            'import_mode': 'auto',
            'page_start': 11,
            'page_end': 30,
        }

        logger.info(f'Testing pages 11-30 with OCR reinit fix...')
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
        diag = result.get('diagnostics', {})
        runtime_failed = diag.get('ocr_runtime_failed_pages', [])
        to_review = result.get('stats', {}).get('to_review', 0)
        errors = result.get('errors', [])

        print(f'\n=== RESULTS ===')
        print(f'Duration: {elapsed:.0f}s')
        print(f'Questions to review: {to_review}')
        print(f'OCR runtime failed pages: {runtime_failed}')
        print(f'Errors: {errors}')
        print(f'Status: {result.get("status")}')

        import sqlite3
        db_c = sqlite3.connect('postgraduate.db')
        qi = db_c.execute('SELECT COUNT(*) FROM question_imports').fetchone()[0]
        print(f'Total question_imports: {qi}')
        db_c.close()

        if runtime_failed:
            print(f'\nFAILED: {len(runtime_failed)} pages had OCR runtime failures')
        else:
            print(f'\nPASSED: No OCR runtime failures')

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == '__main__':
    asyncio.run(main())

"""Full import: all 500 pages in batches with OCR reinit fix."""
import asyncio, json, logging, os, sys, tempfile, time
from datetime import datetime

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['OCR_ENABLED'] = 'true'
os.environ['OCR_USE_GPU'] = 'false'
os.environ['OCR_MAX_WORKERS'] = '1'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('full-import')

from app.core.database import init_db, async_session

BATCH_SIZE = 100  # pages per batch (~100 seconds OCR + pipeline)


async def import_batch(page_start, page_end, batch_label):
    from app.features.pipeline_orchestrator import run_import_pipeline

    pdf_path = '/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf'
    fd, tmp_path = tempfile.mkstemp(prefix=f'import_{batch_label}_', suffix='.pdf')
    try:
        with os.fdopen(fd, 'wb') as f:
            with open(pdf_path, 'rb') as src:
                f.write(src.read())

        pipeline_id = f'full_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{batch_label}'
        options = {
            'enable_ai_repair': True,
            'confidence_threshold': 0.6,
            'import_mode': 'auto',
            'page_start': page_start,
            'page_end': page_end,
        }

        logger.info(f'Batch {batch_label}: pages {page_start}-{page_end}')
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
        s = result.get('stats', {})
        diag = result.get('diagnostics', {})
        logger.info(f'  Done: {elapsed:.0f}s, {s.get("to_review",0)} questions, '
                    f'failed_pages={diag.get("ocr_runtime_failed_pages",[])}')

        return pipeline_id, result
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def main():
    await init_db()

    total_pages = 500
    artifact_dir = '/home/lmh/projects/postgraduate-ai/artifacts/wangdao-os/full-batch'
    os.makedirs(artifact_dir, exist_ok=True)

    all_results = []
    total_questions = 0

    for batch_start in range(1, total_pages + 1, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE - 1, total_pages)
        batch_label = f'p{batch_start:03d}'

        pipeline_id, result = await import_batch(batch_start, batch_end, batch_label)
        all_results.append({
            'batch': batch_label,
            'pages': f'{batch_start}-{batch_end}',
            'pipeline_id': pipeline_id,
        })

        # Save batch result
        with open(f'{artifact_dir}/batch_{batch_label}.json', 'w') as f:
            json.dump({
                'pipeline_id': pipeline_id,
                'result': {k: v for k, v in result.items() if k != 'diagnostics'},
                'runtime_failed_pages': result.get('diagnostics', {}).get('ocr_runtime_failed_pages', []),
            }, f, ensure_ascii=False, indent=2, default=str)

        total_questions += result.get('stats', {}).get('to_review', 0)

    # Summary
    import sqlite3
    db = sqlite3.connect('postgraduate.db')
    cur = db.cursor()
    qi_total = cur.execute('SELECT COUNT(*) FROM question_imports').fetchone()[0]
    db.close()

    summary = {
        'total_pages': total_pages,
        'batches': all_results,
        'total_question_imports': qi_total,
        'total_questions': total_questions,
        'completed_at': datetime.now().isoformat(),
    }
    with open(f'{artifact_dir}/summary.json', 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f'\n{"="*60}')
    print('FULL IMPORT COMPLETE')
    print(f'Total: {qi_total} question_imports, {total_questions} questions')
    print(f'See {artifact_dir}/summary.json')


if __name__ == '__main__':
    asyncio.run(main())

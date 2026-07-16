"""Batch fix shifted options in question_imports.

The structure freeze stage caused a systematic options shift:
question N has question N+1's options. This script shifts them back.
"""
import asyncio, json, logging, os, sys, re

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('fix-options')

from app.core.database import init_db, async_session
from app.services.admin_import_service import update_import_question
from app.schemas.admin_imports import AdminImportQuestionUpdateRequest


async def fix_shifted_options():
    await init_db()

    async with async_session() as db:
        from app.models.question_import import QuestionImport
        from sqlalchemy import select

        # Step 1: Load ALL questions ordered by ID
        rows = (await db.execute(
            select(QuestionImport).order_by(QuestionImport.id)
        )).scalars().all()

        total = len(rows)
        logger.info(f'Loaded {total} questions')

        # Step 2: Build options mapping by shifting
        # Q1's correct options = from its raw or from MCP reference
        # Q2's correct options = Q1's current (stale) options
        # Q3's correct options = Q2's current (stale) options
        # ...

        # Get current options for each question
        current_options = {}
        for r in rows:
            current_options[r.id] = dict(r.parsed_options) if r.parsed_options else {}

        # Build correct mapping
        correct = {}
        ids_in_order = [r.id for r in rows]

        # Q1: extract from raw_text_preview
        option_re = re.compile(r'^([A-Da-d])\s*[.．、:：)）]\s*(.+)', re.MULTILINE)
        q1_preview = rows[0].raw_text_preview or ''
        q1_opts = option_re.findall(q1_preview)
        if q1_opts:
            sorted_opts = {}
            for k, v in q1_opts:
                sorted_opts[k.upper()] = v.strip()
            correct[ids_in_order[0]] = sorted_opts
            logger.info(f'Q1 options from raw_text: {sorted_opts}')
        else:
            # Fallback: known correct options for Q1
            correct[ids_in_order[0]] = {'A': '软件', 'B': '硬件', 'C': '计算机资源', 'D': '应用程序'}
            logger.info('Q1: using known correct options (fallback)')

        # Q2-Q343: shift from previous question's current options
        for i in range(1, total):
            prev_id = ids_in_order[i - 1]
            curr_id = ids_in_order[i]
            correct[curr_id] = dict(current_options.get(prev_id, {}))

        # Step 3: Update each question
        fixed_count = 0
        skip_count = 0
        for r in rows:
            expected = correct.get(r.id, {})
            current = current_options.get(r.id, {})

            if expected == current:
                skip_count += 1
                continue

            try:
                update_data = AdminImportQuestionUpdateRequest(
                    parsed_options=expected,
                    review_note=f"auto-fix: shifted options back (was {json.dumps(current, ensure_ascii=False)})"
                )
                await update_import_question(db, r.id, update_data)
                fixed_count += 1
                if fixed_count <= 5 or fixed_count % 50 == 0:
                    logger.info(f'  Fixed Q{r.id}: {json.dumps(expected, ensure_ascii=False)}')
            except Exception as e:
                logger.error(f'  Failed Q{r.id}: {e}')

        await db.commit()

        logger.info(f'\n=== Fix Complete ===')
        logger.info(f'Total: {total}')
        logger.info(f'Fixed: {fixed_count}')
        logger.info(f'Skipped (no change): {skip_count}')

        # Verify
        verify_rows = (await db.execute(
            select(QuestionImport).order_by(QuestionImport.id).limit(10)
        )).scalars().all()
        logger.info('\nVerification (first 10 questions):')
        for r in verify_rows:
            opts = dict(r.parsed_options) if r.parsed_options else {}
            logger.info(f'  Q{r.id}: {json.dumps(opts, ensure_ascii=False)}')


if __name__ == '__main__':
    asyncio.run(fix_shifted_options())

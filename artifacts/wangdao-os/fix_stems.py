"""Clean header pollution from stems in question_imports."""
import asyncio, json, logging, os, re, sys

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('fix-stems')

from app.core.database import init_db, async_session
from app.services.admin_import_service import update_import_question
from app.schemas.admin_imports import AdminImportQuestionUpdateRequest

# Known noise patterns in stems (in order: remove more specific first)
NOISE_PATTERNS = [
    # Page header / watermark
    (re.compile(r'[。，]?风中易小生24考研计算机WD操作系统做题本【选择题】'), ''),
    (re.compile(r'【微信公众号:风中易小生】'), ''),
    (re.compile(r'风中易小生24考研计算机WD操作系统做题本【选择题】[。，]?'), ''),
    # Section headers at end of stem (common pattern: end of section on same page)
    (re.compile(r'\n1\.\d+[^。\n]{0,20}$'), ''),  # trailing "1.3 操作系统运行环境"
    (re.compile(r'\n第[一二三四五六七八九十]+章[^。\n]{0,30}$'), ''),  # trailing chapter headers
    # Partial section header at end
    (re.compile(r'\n1\.\d[^。\n]{0,15}$'), ''),
    # "；寄存" noise from split error
    (re.compile(r'\n;产生软中断\n;寄存器'), ''),
    # Trailing garbled text
    (re.compile(r'\n正\n?$'), ''),
]


async def fix_stems():
    await init_db()
    async with async_session() as db:
        from app.models.question_import import QuestionImport
        from sqlalchemy import select

        rows = (await db.execute(
            select(QuestionImport).order_by(QuestionImport.id)
        )).scalars().all()

        fixed = 0
        for r in rows:
            pc = dict(r.parsed_content) if r.parsed_content else {}
            stem = pc.get('text', '') if isinstance(pc, dict) else ''
            if not stem:
                continue

            original = stem
            for pat, replacement in NOISE_PATTERNS:
                stem = pat.sub(replacement, stem)
            stem = stem.strip()

            if stem == original:
                continue

            try:
                # Clean up trailing punctuation from removals
                stem = re.sub(r'[。，]+$', '', stem).strip()
                if stem.endswith('】'):
                    stem = stem[:-1].strip()

                update_data = AdminImportQuestionUpdateRequest(
                    parsed_content={'text': stem},
                    review_note=f"auto-fix: removed header noise from stem"
                )
                await update_import_question(db, r.id, update_data)
                fixed += 1
                if fixed <= 10:
                    logger.info(f'  Q{r.id}: cleaned stem')
                    logger.info(f'    Before: {original[:80]}')
                    logger.info(f'    After:  {stem[:80]}')
            except Exception as e:
                logger.warning(f'  Q{r.id}: failed - {e}')

        await db.commit()
        logger.info(f'\nFixed {fixed}/{len(rows)} stems')


if __name__ == '__main__':
    asyncio.run(fix_stems())

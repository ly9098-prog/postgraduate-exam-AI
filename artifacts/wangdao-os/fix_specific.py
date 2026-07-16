"""Fix specific garbled questions using edit API + MCP OCR reference."""
import asyncio, json, logging, os, sys

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('fix-specific')

from app.core.database import init_db, async_session
from app.services.admin_import_service import update_import_question
from app.schemas.admin_imports import AdminImportQuestionUpdateRequest

# Known correct content from MCP OCR verification
# Format: {question_id: (correct_stem, correct_options_dict)}
FIXES = {
    # Q341: disk partition question with I/II/IV options
    341: (
        "对磁盘进行分区\n"
        "I.建立文件系统的根目录\n"
        "II.确定磁盘扇区校验码所占位数\n"
        "IV.对保存空闲磁盘块信息的数据结构进行初始化",
        {"A": "仅 II", "B": "仅 II、IV", "C": "仅 III、IV", "D": "仅 I、II、IV"}
    ),
}

# Questions with I/II/III/IV options that need cleanup (garbled in pipeline)
# Format: {qid: correct_options} - stems are OK, just fix the garbled Roman numeral options
ROMAN_OPTION_FIXES = {
    # Q33: 批处理系统 I/II/III
    33: None,  # will fix from raw_text_preview
    34: None,
    70: None,
    145: None,
    176: None,
    188: None,
    202: None,
}

# Questions with section header in stem (need cleanup)
SECTION_HEADER_FIXES = {
    326: ("磁盘上的文件以( )为单位读/写。", None),
    327: ("在磁盘中读取数据的下列时间中，影响最大的是()。", None),
    328: ("硬盘的操作系统引导扇区产生在()。", None),
}


async def fix_question(db, qid, stem, options, note=""):
    """Fix a single question's stem and options."""
    try:
        update_data = AdminImportQuestionUpdateRequest(
            parsed_content={'text': stem} if stem else None,
            parsed_options=options if options else None,
            review_note=f"auto-fix: {note}" if note else "auto-fix: restored from MCP OCR"
        )
        await update_import_question(db, qid, update_data)
        logger.info(f'  Q{qid}: fixed - {stem[:50] if stem else ""} opts={json.dumps(options, ensure_ascii=False)[:60] if options else "N/A"}')
        return True
    except Exception as e:
        logger.error(f'  Q{qid}: FAILED - {e}')
        return False


async def main():
    await init_db()
    async with async_session() as db:
        from app.models.question_import import QuestionImport
        from sqlalchemy import select
        import re

        fixed = 0

        # Fix Q341 (disk partition + next question merged)
        for qid, (stem, opts) in FIXES.items():
            if await fix_question(db, qid, stem, opts, "disk partition question"):
                fixed += 1

        # Fix section headers in late questions
        for qid, (stem, _) in SECTION_HEADER_FIXES.items():
            if await fix_question(db, qid, stem, None, "removed section header"):
                fixed += 1

        # Fix I/II/III/IV questions: parse from raw_text_preview
        # These questions have correct stem but garbled Roman numeral options
        iiv_rows = (await db.execute(
            select(QuestionImport).where(QuestionImport.id.in_(ROMAN_OPTION_FIXES.keys()))
        )).scalars().all()

        for r in iiv_rows:
            preview = r.raw_text_preview or ''
            # Extract options: pattern like "D.仅 I、II、IV" or "A.仅 II"
            opt_pattern = re.compile(
                r'([A-Da-d])\s*[.．、:：)）]\s*(仅\s*(?:[IⅢ]+、?\s*)*[IⅢ]+(?:\s*、\s*[IⅢ]+)*)'
            )
            matches = opt_pattern.findall(preview)
            if len(matches) == 4:
                corrected = {}
                for k, v in matches:
                    corrected[k.upper()] = v.strip()
                if await fix_question(db, r.id, None, corrected, "restored Roman numeral options"):
                    fixed += 1
            else:
                logger.warning(f'  Q{r.id}: found {len(matches)} option matches, expected 4')

        await db.commit()
        logger.info(f'Fixed {fixed} specific questions')

        # Verify Q341
        r = (await db.execute(
            select(QuestionImport).where(QuestionImport.id == 341)
        )).scalar_one()
        pc = r.parsed_content or {}
        stem = pc.get('text', '') if isinstance(pc, dict) else str(pc)
        opts = r.parsed_options or {}
        logger.info(f'\nQ341 after fix:')
        logger.info(f'  Stem: {stem[:80]}')
        logger.info(f'  Options: {json.dumps(opts, ensure_ascii=False)}')


if __name__ == '__main__':
    asyncio.run(main())

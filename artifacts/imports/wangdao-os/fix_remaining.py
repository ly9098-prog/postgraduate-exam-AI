"""Fix remaining garbled questions using MCP OCR page lookup."""
import asyncio, json, logging, os, sys, re

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('fix-remaining')

from app.core.database import init_db, async_session
from app.services.admin_import_service import update_import_question
from app.schemas.admin_imports import AdminImportQuestionUpdateRequest


OPTION_RE = re.compile(r'^([A-Da-d])\s*[.．、:：)）]\s*(.+)', re.MULTILINE)


def parse_options(text):
    """Extract ABCD options from OCR text, handling scrambled order."""
    matches = OPTION_RE.findall(text)
    result = {}
    for k, v in matches:
        key = k.upper()
        val = v.strip().rstrip('。，;；')
        if key in 'ABCD' and val and len(val) > 1:
            result[key] = val
    return result


async def fix_q(db, qid, stem=None, options=None, answer=None, note=""):
    try:
        kwargs = {}
        if stem: kwargs['parsed_content'] = {'text': stem}
        if options: kwargs['parsed_options'] = options
        if answer: kwargs['answer'] = answer
        kwargs['review_note'] = f"auto-fix: {note}" if note else "auto-fix"
        update_data = AdminImportQuestionUpdateRequest(**kwargs)
        await update_import_question(db, qid, update_data)
        logger.info(f'  Q{qid}: OK - {note}')
        return True
    except Exception as e:
        logger.error(f'  Q{qid}: FAILED - {e}')
        return False


async def main():
    await init_db()
    async with async_session() as db:
        from app.models.question_import import QuestionImport
        from sqlalchemy import select
        import re as re_mod

        fixed = 0

        # ── Group A: Options in raw_text_preview, just need proper extraction ──

        # Q37: "处理器执行的指令被分为两类"
        # raw: "B.联机用户 D.操作系统 C.目标程序 A.操作员"
        # Wait - the stem is about 特权指令 which only OS can execute. Answer = 操作系统
        # Options from raw: 操作员, 联机用户, 目标程序, 操作系统
        # Correct mapping from context: A.操作员 B.联机用户 C.目标程序 D.操作系统
        q37_opts = {"A": "操作员", "B": "联机用户", "C": "目标程序", "D": "操作系统"}
        stem37 = "处理器执行的指令被分为两类，其中有一类称为特权指令，它只允许()使用。"
        if await fix_q(db, 37, stem=stem37, options=q37_opts, note="restored from raw_text"):
            fixed += 1

        # Q177: "死锁检测时检查的是()"
        # raw: "A.资源有向图 B.前驱图 D.安全图 C.搜索树"
        q177_opts = {"A": "资源有向图", "B": "前驱图", "C": "搜索树", "D": "安全图"}
        if await fix_q(db, 177, options=q177_opts, note="restored ABCD order from raw"):
            fixed += 1

        # Q182: "可重入程序是通过()方法"
        # raw: "A.改变时间片长度 B.改变用户数 C.提高对换速度 D.减少对换数量"
        stem182 = "可重入程序是通过( )方法来改善系统性能的。"
        q182_opts = {"A": "改变时间片长度", "B": "改变用户数", "C": "提高对换速度", "D": "减少对换数量"}
        if await fix_q(db, 182, stem=stem182, options=q182_opts, note="restored from raw_text"):
            fixed += 1

        # Q203: has section header in stem
        stem203 = "【2009统考真题】一个分段存储管理系统中，地址长度为32位，其中段号占8位，则最大段长是()。"
        # Need to find the options from raw_data or MCP OCR
        if await fix_q(db, 203, stem=stem203, note="removed section header from stem"):
            fixed += 1

        # ── Group B: Need MCP OCR page lookup ──
        # For these, extract what we can from raw_text_preview

        # Q36: I/II/III question - raw shows "D. I、II、III"
        # III is "需要运行在多CPU的硬件平台上", missing II content
        # The options from raw are incomplete. Need page lookup.

        # Q57: I/II/III/IV about 系统调用. The raw_text has all 4 options but Roman numerals garbled
        # Let me check if I can extract from raw_text
        r57 = (await db.execute(select(QuestionImport).where(QuestionImport.id == 57))).scalar_one()
        preview57 = r57.raw_text_preview or ''
        # Raw shows: "IV.系统调用是操作系统内核为应用程序提供服务的接口 I、I"
        # Options seem to be: A.仅 I、II、III  or similar
        opt57 = re_mod.findall(r'([A-Da-d])\s*[.．、:：)）]\s*(仅\s*[IⅢ、IV、 ]+)', preview57)
        if len(opt57) == 4:
            fixed_opts57 = {k.upper(): v.strip() for k, v in opt57}
            if await fix_q(db, 57, options=fixed_opts57, note="restored Roman numeral options"):
                fixed += 1
        else:
            logger.info(f'  Q57: need MCP OCR - found {len(opt57)} option matches')

        # Q121: has 5 options, likely merged 2 questions
        # "三个同时到达的作业" - need page lookup

        # Q176: PV操作 I/II/III/IV - has all content in raw_text
        r176 = (await db.execute(select(QuestionImport).where(QuestionImport.id == 176))).scalar_one()
        preview176 = r176.raw_text_preview or ''
        opt176 = re_mod.findall(r'([A-Da-d])\s*[.．、:：)）]\s*(仅?\s*[IⅢ、IV、 ]+)', preview176)
        if len(opt176) == 4:
            fixed_opts176 = {k.upper(): v.strip() for k, v in opt176}
            if await fix_q(db, 176, options=fixed_opts176, note="restored Roman numeral options"):
                fixed += 1
        else:
            logger.info(f'  Q176: need MCP OCR - found {len(opt176)} option matches')

        # Q202: 页式存储 I/II/III/IV
        r202 = (await db.execute(select(QuestionImport).where(QuestionImport.id == 202))).scalar_one()
        preview202 = r202.raw_text_preview or ''
        opt202 = re_mod.findall(r'([A-Da-d])\s*[.．、:：)）]\s*(仅?\s*[IⅢ、IV、 ]+)', preview202)
        if len(opt202) == 4:
            fixed_opts202 = {k.upper(): v.strip() for k, v in opt202}
            if await fix_q(db, 202, options=fixed_opts202, note="restored Roman numeral options"):
                fixed += 1
        else:
            logger.info(f'  Q202: need MCP OCR - found {len(opt202)} option matches')

        await db.commit()

        # Final summary
        rows = (await db.execute(
            select(QuestionImport).order_by(QuestionImport.id)
        )).scalars().all()
        total = len(rows)
        full = sum(1 for r in rows if r.parsed_options and len(r.parsed_options) == 4)
        partial = sum(1 for r in rows if r.parsed_options and 0 < len(r.parsed_options) < 4)
        no_opts = sum(1 for r in rows if not r.parsed_options or len(r.parsed_options) == 0)

        logger.info(f'\n=== Final Status ===')
        logger.info(f'Fixed this round: {fixed}')
        logger.info(f'Total: {total}')
        logger.info(f'4 options: {full} ({(full/total*100):.0f}%)')
        logger.info(f'Partial: {partial}')
        logger.info(f'No options: {no_opts}')

        if partial + no_opts > 0:
            logger.info(f'\nStill need MCP OCR lookup:')
            for r in rows:
                if not r.parsed_options or len(r.parsed_options) != 4:
                    pc = r.parsed_content or {}
                    stem = pc.get('text','')[:60] if isinstance(pc, dict) else ''
                    logger.info(f'  Q{r.id} ({len(r.parsed_options or [])} opts): {stem}')


if __name__ == '__main__':
    asyncio.run(main())

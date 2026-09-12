"""Final fix: correct all remaining garbled questions from MCP OCR data."""
import asyncio, json, logging, os, sys

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('fix-final')

from app.core.database import init_db, async_session
from app.services.admin_import_service import update_import_question
from app.schemas.admin_imports import AdminImportQuestionUpdateRequest


FIXES = {
    # Q36 (page 35): 多任务操作系统 I/II/III
    36: {
        'stem': "【2018统考真题】下列关于多任务操作系统的叙述中，正确的是()。\n"
                "I.具有并发和并行的特点\n"
                "II.需要实现对共享资源的保护\n"
                "III.需要运行在多CPU的硬件平台上",
        'options': {"A": "仅I", "B": "仅II", "C": "仅I、II", "D": "I、II、III"}
    },
    # Q57 (page 62): 系统调用 I/II/III/IV
    57: {
        'stem': "【2019统考真题】下列关于系统调用的叙述中，正确的是()。\n"
                "I.在执行系统调用服务程序的过程中，CPU处于内核态\n"
                "II.操作系统通过提供系统调用避免用户程序直接访问外设\n"
                "III.不同的操作系统为应用程序提供了统一的系统调用接口\n"
                "IV.系统调用是操作系统内核为应用程序提供服务的接口",
        'options': {"A": "仅I、IV", "B": "仅I、III", "C": "仅I、II、IV", "D": "仅I、III、IV"}
    },
    # Q121 (page 147): 短作业优先调度
    121: {
        'stem': "现在有三个同时到达的作业J1,J2和J3,它们的执行时间分别是T1,T2,T3,且T1<T2<T3。"
                "系统按单道方式运行且采用短作业优先调度算法，则平均周转时间是()。",
        'options': {
            "A": "T1+T2+T3",
            "B": "(3T1+2T2+T3)/3",
            "C": "(T1+T2+T3)/3",
            "D": "(T1+2T2+3T3)/3"
        }
    },
    # Q176 (page 206): PV操作 I/II/III/IV
    176: {
        'stem': "下列关于PV操作的说法中，正确的是()。\n"
                "I.PV操作是一种系统调用命令\n"
                "II.PV操作是一种低级进程通信原语\n"
                "III.PV操作是由一个不可被中断的过程组成\n"
                "IV.PV操作是由两个不可被中断的过程组成",
        'options': {"A": "I、III", "B": "II、IV", "C": "I、II、IV", "D": "I、IV"}
    },
    # Q202 (page 304): 页式存储 I/II/III/IV
    202: {
        'stem': "下列关于页式存储的论述中，正确的是()。\n"
                "I.在页式存储管理中，若关闭TLB，则每当访问一条指令或存取一个操作数时都要访问2次内存\n"
                "II.页式存储管理不会产生内部碎片\n"
                "III.页式存储管理中的页面是为用户所感知的\n"
                "IV.页式存储方式可以采用静态重定位",
        'options': {"A": "I、II、IV", "B": "I、IV", "C": "仅I", "D": "全都正确"}
    },
    # Q203 (page 306): 分段存储管理
    203: {
        'stem': "【2009统考真题】一个分段存储管理系统中，地址长度为32位，其中段号占8位，则最大段长是()。",
        'options': {"A": "2^8B", "B": "2^16B", "C": "2^24B", "D": "2^32B"}
    },
    # Q326 (page 481): 磁盘文件单位
    326: {
        'stem': "磁盘上的文件以( )为单位读/写。",
        'options': {"A": "块", "B": "记录", "C": "柱面", "D": "磁道"}
    },
}


async def main():
    await init_db()
    async with async_session() as db:
        from app.models.question_import import QuestionImport
        from sqlalchemy import select

        fixed = 0
        for qid, data in FIXES.items():
            try:
                r = (await db.execute(
                    select(QuestionImport).where(QuestionImport.id == qid)
                )).scalar_one_or_none()
                if not r:
                    logger.warning(f'Q{qid}: not found')
                    continue

                update_data = AdminImportQuestionUpdateRequest(
                    parsed_content={'text': data['stem']},
                    parsed_options=data['options'],
                    review_note=f"auto-fix: restored from MCP OCR page lookup"
                )
                await update_import_question(db, qid, update_data)
                fixed += 1
                logger.info(f'Q{qid}: OK - {data["stem"][:50]}...')
            except Exception as e:
                logger.error(f'Q{qid}: FAILED - {e}')

        await db.commit()

        # Final verification
        rows = (await db.execute(
            select(QuestionImport).order_by(QuestionImport.id)
        )).scalars().all()
        total = len(rows)
        full = sum(1 for r in rows if r.parsed_options and len(r.parsed_options) == 4)
        partial = sum(1 for r in rows if r.parsed_options and 0 < len(r.parsed_options) < 4)
        no_opts = sum(1 for r in rows if not r.parsed_options or len(r.parsed_options) == 0)

        logger.info(f'\n=== Final Import Quality ===')
        logger.info(f'Fixed this round: {fixed}')
        logger.info(f'Total questions: {total}')
        logger.info(f'4 options: {full} ({(full/total*100):.1f}%)')
        logger.info(f'Partial options: {partial}')
        logger.info(f'No options: {no_opts}')
        logger.info(f'All answers: missing (correct - PDF has no answers)')


if __name__ == '__main__':
    asyncio.run(main())

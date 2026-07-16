import asyncio, json, sys

sys.path.insert(0, '.')
from sqlalchemy import text
from app.core.database import init_db, async_session


async def main():
    await init_db()
    async with async_session() as db:
        ids = [17, 33, 34, 35, 51, 54, 58, 59, 60, 63, 64, 119, 134, 138, 141, 142, 144, 146, 147, 171, 227, 249, 250, 251, 258, 327, 328, 329, 330, 331, 332, 333, 334, 335, 336, 337, 338, 339, 340, 341, 342, 343]

        result = await db.execute(
            text(f"SELECT id, parsed_content, parsed_options FROM question_imports WHERE id IN ({','.join(str(i) for i in ids)}) ORDER BY id")
        )

        for r in result:
            qid = r[0]
            content_s = r[1] or '{}'
            try:
                content = json.loads(content_s) if isinstance(content_s, str) else (content_s or {})
            except:
                content = {}
            stem = content.get("text", "") if isinstance(content, dict) else ""

            opts_s = r[2] or '{}'
            try:
                opts = json.loads(opts_s) if isinstance(opts_s, str) else (opts_s or {})
            except:
                opts = {}

            print(f"{'='*55}")
            print(f"Q{qid}")
            print(f"  {stem[:130]}")
            if len(stem) > 130:
                print(f"  {stem[130:220]}")
            for k in sorted(opts.keys()):
                print(f"    {k}: {opts[k]}")
            print()


asyncio.run(main())

"""清除本地数据库中所有题目数据和审核数据。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["RUN_ENV"] = "dev"

from app.core.database import engine
from sqlalchemy import text


async def clear():
    async with engine.connect() as conn:
        # Get existing tables
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        existing = {row[0] for row in result.fetchall()}
        print(f"Existing tables ({len(existing)}): {', '.join(sorted(existing))}")

        await conn.execute(text("PRAGMA foreign_keys = OFF;"))

        tables = [
            "review_records",
            "review_schedules",
            "wrong_questions",
            "question_versions",
            "ai_generation_logs",
            "audit_logs",
            "question_imports",
            "import_batch_job_items",
            "import_batch_jobs",
            "import_pipeline_chunks",
            "import_pipelines",
            "questions",
        ]

        total = 0
        for table in tables:
            if table not in existing:
                print(f"  SKIP {table}: table does not exist")
                continue
            result = await conn.execute(text(f"DELETE FROM {table}"))
            print(f"  CLEARED {table}: {result.rowcount} rows")
            total += result.rowcount

        await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.commit()

    engine.dispose()
    print(f"\nDone. Total {total} rows cleared from {len(tables)} tables.")


if __name__ == "__main__":
    print("Clearing question data and audit data from local database...")
    asyncio.run(clear())

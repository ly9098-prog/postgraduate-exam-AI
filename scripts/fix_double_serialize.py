"""Fix double-serialized JSON fields in question_imports."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import async_session
from app.models.question_import import QuestionImport
from sqlalchemy import select
from datetime import datetime, timezone

async def main():
    async with async_session() as db:
        result = await db.execute(
            select(QuestionImport).where(QuestionImport.id.in_([2, 9, 10]))
        )
        items = result.scalars().all()

        for qi in items:
            # Fix parsed_options if it's a string instead of dict
            if isinstance(qi.parsed_options, str):
                try:
                    parsed = json.loads(qi.parsed_options)
                    if isinstance(parsed, dict):
                        qi.parsed_options = parsed
                        print(f"ID={qi.id}: fixed double-serialized options")
                except:
                    pass

            # Fix parsed_content if needed
            if isinstance(qi.parsed_content, str):
                try:
                    parsed = json.loads(qi.parsed_content)
                    if isinstance(parsed, dict):
                        qi.parsed_content = parsed
                        print(f"ID={qi.id}: fixed double-serialized content")
                except:
                    pass

            qi.updated_at = datetime.now(timezone.utc)

        await db.commit()
        print("All double-serialization fixes committed")

        # Verify
        result2 = await db.execute(
            select(QuestionImport).where(QuestionImport.id.in_([2, 9, 10]))
        )
        for qi in result2.scalars().all():
            print(f"ID={qi.id}: options type={type(qi.parsed_options).__name__}, content type={type(qi.parsed_content).__name__}")

asyncio.run(main())

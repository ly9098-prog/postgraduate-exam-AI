#!/usr/bin/env python3
"""Verify prod question_hash consistency for a list of sync_uuids."""
import asyncio, json, os, sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.features.question_pipeline import normalizer

UUIDS = [
    "e9613613-5673-4892-8639-d981052f50bb", "0ef1ba22-4fe2-4d5b-b1b6-c438489024d9",
    "3442257b-86b3-4826-9d64-cd6c6bb679b7", "dcb7d505-52a4-40e6-8eb8-4842da383216",
    "cf4c667f-32df-44a1-bcf3-3d97c2d4833d", "2ec39bc4-b835-4672-ae98-3aabd0b15524",
    "df95a096-bf2b-485a-8ce7-535f904de0b8", "0f05cb04-32f8-434c-af53-88441c18cdb9",
    "046cef8d-1a9d-45c9-a318-9e1e23a60927", "c9fe1bb9-b617-40c1-a678-19d1272527b4",
    "c18911a6-568d-4a80-bce6-a4c436d23761", "89c86165-0f2a-4081-8137-881c892bd5b8",
    "4c4ac357-2acb-4209-94e8-586e47ecbd47", "49523936-05e6-4887-9986-2c39ae304bfb",
    "a7b73d5d-499b-4004-9a57-e1272dda3522", "68baa7a9-4a73-4ee3-9730-ff596026944b",
    "46b1f6e7-08fa-458c-9158-dc6f6f904768", "4173b976-8f44-4ea3-8a31-764ce0ddd3cd",
    "68aba918-259c-47e2-b6c0-4a076d04b02a", "bf6832dc-b2b8-4feb-ab31-ba3ad454a4ac",
    "39c875ab-9771-4aab-a2ec-cd245e06b9f3", "6303ca0c-ba83-4941-865b-5092ddfeb1bf",
    "22f8059e-bcdb-465f-8343-0e24cb9cab70", "4d052eef-7215-4c14-96c0-da00a8a9c307",
    "ab35805f-7037-443f-b6cd-a8ca35891931", "705ea4d0-ce9e-47b5-a907-60901d04c732",
    "e7162fb5-ead0-4a9d-b445-dba035f53c67", "781ef3a2-8436-43ed-88e6-d1da6eb07869",
    "5c7a089c-a159-4def-8cea-3dac8afbc650", "68e694f0-20e6-42ea-a2a1-0617858163d0",
    "71c8a9df-8ae4-4228-a5c0-0e0606c98753", "b787791a-acdf-4ed7-91b7-f54755bf3685",
    "ae30d6b4-9d04-4f10-bd93-73d194c71d3e", "869d1fdb-6877-4015-ac24-1161f5fcae5c",
    "de3c22ad-8fce-49fb-a666-825732881176",
]


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    S = sessionmaker(engine, class_=AsyncSession)
    async with S() as s:
        ph = ",".join(f":u{i}" for i in range(len(UUIDS)))
        params = {f"u{i}": u for i, u in enumerate(UUIDS)}
        rows = (await s.execute(
            text(f"SELECT id, sync_uuid, content, options, answer, question_hash "
                 f"FROM questions WHERE sync_uuid IN ({ph})"), params
        )).fetchall()
        ok = 0
        for r in rows:
            content = r.content if isinstance(r.content, dict) else json.loads(r.content)
            opts = r.options if isinstance(r.options, dict) else json.loads(r.options)
            h = normalizer.build_question_hash(content.get("text", ""), opts, r.answer)
            status = "OK" if h == r.question_hash else "MISMATCH"
            if h == r.question_hash:
                ok += 1
            print(f"id={r.id} {status} {h[:12]}")
        print(f"\n{ok}/{len(rows)} hash consistent")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

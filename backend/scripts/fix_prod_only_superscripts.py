#!/usr/bin/env python3
"""生产库独有 18 道的上标化修复（本地不存在，直接在生产库按 sync_uuid 就地修复）。

与 fix_superscripts.py 同一套转换规则；question_hash 用容器内 app 的 normalizer 重算。
只处理下表中列出的 sync_uuid，按 sync_uuid 匹配，严禁使用 numeric id。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

PROD_ONLY_UUIDS = [
    "e9613613-5673-4892-8639-d981052f50bb",
    "0ef1ba22-4fe2-4d5b-b1b6-c438489024d9",
    "3442257b-86b3-4826-9d64-cd6c6bb679b7",
    "dcb7d505-52a4-40e6-8eb8-4842da383216",
    "cf4c667f-32df-44a1-bcf3-3d97c2d4833d",
    "2ec39bc4-b835-4672-ae98-3aabd0b15524",
    "df95a096-bf2b-485a-8ce7-535f904de0b8",
    "0f05cb04-32f8-434c-af53-88441c18cdb9",
    "046cef8d-1a9d-45c9-a318-9e1e23a60927",
    "c9fe1bb9-b617-40c1-a678-19d1272527b4",
    "c18911a6-568d-4a80-bce6-a4c436d23761",
    "89c86165-0f2a-4081-8137-881c892bd5b8",
    "4c4ac357-2acb-4209-94e8-586e47ecbd47",
    "49523936-05e6-4887-9986-2c39ae304bfb",
    "a7b73d5d-499b-4004-9a57-e1272dda3522",
    "68baa7a9-4a73-4ee3-9730-ff596026944b",
    "46b1f6e7-08fa-458c-9158-dc6f6f904768",
    "4173b976-8f44-4ea3-8a31-764ce0ddd3cd",
]


def superscriptize(s: str) -> str:
    s = re.sub(r"\^\(([^()]*)\)", lambda m: "^{" + m.group(1) + "}", s)
    # 数字指数（含符号）：2^32 → 2^{32}，2^8B → 2^{8}B（B 是单位，不进指数）
    s = re.sub(r"\^([+-]?\d+)", lambda m: "^{" + m.group(1) + "}", s)
    # 字母指数：2^n → 2^{n}，2^h+1 → 2^{h}+1
    s = re.sub(r"\^([A-Za-z]+)", lambda m: "^{" + m.group(1) + "}", s)
    return s


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from app.features.question_pipeline import normalizer  # noqa: E402

    engine = create_async_engine(args.target, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    changed, unchanged, missing = [], 0, []

    async with Session() as s:
        for uuid in PROD_ONLY_UUIDS:
            row = (
                await s.execute(
                    text(
                        "SELECT id, content, options, answer, question_hash "
                        "FROM questions WHERE sync_uuid = :u"
                    ),
                    {"u": uuid},
                )
            ).fetchone()
            if row is None:
                missing.append(uuid)
                continue
            content = row.content if isinstance(row.content, dict) else json.loads(row.content)
            stem = content.get("text", "")
            opts = row.options if isinstance(row.options, dict) else json.loads(row.options)
            new_opts = {}
            for k, v in opts.items():
                new_opts[k] = superscriptize(str(v)) if isinstance(v, str) else v
            if new_opts == opts:
                unchanged += 1
                print(f"uuid={uuid} prod_id={row.id}: options 无变化，跳过")
                continue
            new_hash = normalizer.build_question_hash(stem, new_opts, row.answer)
            print(f"uuid={uuid} prod_id={row.id}")
            print(f"  options: {json.dumps(opts, ensure_ascii=False)[:100]}")
            print(f"       →  {json.dumps(new_opts, ensure_ascii=False)[:100]}")
            print(f"  hash: {row.question_hash} → {new_hash}")
            if args.apply:
                await s.execute(
                    text(
                        "UPDATE questions SET options = :opts, question_hash = :h, "
                        "sync_version = sync_version + 1, updated_at = :now "
                        "WHERE sync_uuid = :u"
                    ),
                    {"opts": json.dumps(new_opts, ensure_ascii=False),
                     "h": new_hash, "now": now, "u": uuid},
                )
                changed.append(uuid)

        if args.apply:
            await s.commit()

    print("\n===== 生产独有 18 道修复报告 =====")
    print(f"  已修改: {len(changed)}")
    print(f"  无变化: {unchanged}")
    print(f"  生产缺失: {len(missing)}")
    for u in missing:
        print(f"    - {u}")
    print(f"  模式: {'APPLY（已写入）' if args.apply else 'DRY-RUN（未写入）'}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio_run = __import__("asyncio").run
    asyncio_run(main())

#!/usr/bin/env python3
"""按 sync_uuid 把本地 17 道上标化修复同步到生产 PostgreSQL。

身份匹配只用 sync_uuid —— 严禁使用 numeric id（本地与生产 id 不一致）。
只更新本地已修复的 17 行：options / question_hash / sync_version+1 / updated_at。

用法（目标库需在容器内解析 DATABASE_URL）：
    # Dry run（默认，只读）
    python scripts/sync_question_superscripts_to_prod.py \
        --source sqlite+aiosqlite:///./postgraduate.db \
        --target "$DATABASE_URL"

    # Apply
    ... --target "$DATABASE_URL" --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_ENV", "development")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

# 本地扫描确认的 17 道题（幂次全部在 options）
AFFECTED_UUIDS = [
    "68aba918-259c-47e2-b6c0-4a076d04b02a",
    "bf6832dc-b2b8-4feb-ab31-ba3ad454a4ac",
    "39c875ab-9771-4aab-a2ec-cd245e06b9f3",
    "6303ca0c-ba83-4941-865b-5092ddfeb1bf",
    "22f8059e-bcdb-465f-8343-0e24cb9cab70",
    "4d052eef-7215-4c14-96c0-da00a8a9c307",
    "ab35805f-7037-443f-b6cd-a8ca35891931",
    "705ea4d0-ce9e-47b5-a907-60901d04c732",
    "e7162fb5-ead0-4a9d-b445-dba035f53c67",
    "781ef3a2-8436-43ed-88e6-d1da6eb07869",
    "5c7a089c-a159-4def-8cea-3dac8afbc650",
    "68e694f0-20e6-42ea-a2a1-0617858163d0",
    "71c8a9df-8ae4-4228-a5c0-0e0606c98753",
    "b787791a-acdf-4ed7-91b7-f54755bf3685",
    "ae30d6b4-9d04-4f10-bd93-73d194c71d3e",
    "869d1fdb-6877-4015-ac24-1161f5fcae5c",
    "de3c22ad-8fce-49fb-a666-825732881176",
]


def _coerce_datetime(val):
    if val is None or isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


class QuestionSuperscriptSyncer:
    def __init__(self, source_url: str, target_url: str, dry_run: bool = True):
        self.source_url = source_url
        self.target_url = target_url
        self.dry_run = dry_run
        self.stats = {
            "found": 0, "updated": 0, "missing_in_prod": 0, "missing_local": 0,
            "warnings": [],
        }

    def _init_engines(self):
        self.source_engine = create_async_engine(self.source_url, echo=False)
        self.target_engine = create_async_engine(self.target_url, echo=False)
        self.SourceSession = sessionmaker(
            self.source_engine, class_=AsyncSession, expire_on_commit=False
        )
        self.TargetSession = sessionmaker(
            self.target_engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self):
        await self.source_engine.dispose()
        await self.target_engine.dispose()

    async def _load_local_rows(self):
        ph = ",".join(f":u{i}" for i in range(len(AFFECTED_UUIDS)))
        params = {f"u{i}": u for i, u in enumerate(AFFECTED_UUIDS)}
        async with self.SourceSession() as s:
            r = await s.execute(
                text(
                    f"SELECT sync_uuid, options, question_hash, sync_version, "
                    f"updated_at FROM questions WHERE sync_uuid IN ({ph})"
                ),
                params,
            )
            cols = r.keys()
            rows = [dict(zip(cols, row)) for row in r.fetchall()]
        return {row["sync_uuid"]: row for row in rows}

    async def sync(self):
        local_rows = await self._load_local_rows()
        missing_local = [u for u in AFFECTED_UUIDS if u not in local_rows]
        self.stats["missing_local"] = len(missing_local)
        for u in missing_local:
            self.stats["warnings"].append(f"本地缺 sync_uuid={u}")

        async with self.TargetSession() as t:
            for uuid in AFFECTED_UUIDS:
                local = local_rows.get(uuid)
                if local is None:
                    continue
                prod_row = (
                    await t.execute(
                        text(
                            "SELECT id, options, question_hash, sync_version, updated_at "
                            "FROM questions WHERE sync_uuid = :u"
                        ),
                        {"u": uuid},
                    )
                ).fetchone()
                if prod_row is None:
                    self.stats["missing_in_prod"] += 1
                    self.stats["warnings"].append(f"生产缺 sync_uuid={uuid}")
                    continue

                self.stats["found"] += 1
                raw_opts = local["options"]
                opts_dict = json.loads(raw_opts) if isinstance(raw_opts, str) else raw_opts
                new_opts = json.dumps(opts_dict, ensure_ascii=False)
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                old_opts = json.dumps(prod_row.options, ensure_ascii=False)

                print(f"uuid={uuid} prod_id={prod_row.id}")
                print(f"  options: {old_opts[:100]}")
                print(f"       →  {new_opts[:100]}")
                print(f"  hash: {prod_row.question_hash} → {local['question_hash']}")
                print(f"  version: {prod_row.sync_version} → {prod_row.sync_version + 1}")

                if self.dry_run:
                    continue

                await t.execute(
                    text(
                        "UPDATE questions SET options = :opts, question_hash = :h, "
                        "sync_version = sync_version + 1, updated_at = :now "
                        "WHERE sync_uuid = :u"
                    ),
                    {
                        "opts": new_opts,
                        "h": local["question_hash"],
                        "now": now,
                        "u": uuid,
                    },
                )
                self.stats["updated"] += 1

            if not self.dry_run:
                await t.commit()

    def report(self):
        print("\n===== 同步报告 =====")
        print(f"  生产匹配: {self.stats['found']}")
        print(f"  已更新:   {self.stats['updated']}")
        print(f"  生产缺失: {self.stats['missing_in_prod']}")
        print(f"  本地缺失: {self.stats['missing_local']}")
        if self.stats["warnings"]:
            print("  警告:")
            for w in self.stats["warnings"]:
                print(f"    - {w}")
        print(f"  模式: {'DRY-RUN（未写入）' if self.dry_run else 'APPLY（已写入）'}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    syncer = QuestionSuperscriptSyncer(args.source, args.target, dry_run=not args.apply)
    syncer._init_engines()
    try:
        await syncer.sync()
        syncer.report()
    finally:
        await syncer.close()


if __name__ == "__main__":
    asyncio.run(main())

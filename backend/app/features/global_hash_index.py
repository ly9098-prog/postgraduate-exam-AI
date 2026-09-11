"""GlobalHashIndex — 跨 chunk 共享的题目去重索引（P2-4）。

similarity_match 阶段以前每个 chunk 都对当前 subject 整张题库做一次
``SELECT id, content, options, answer FROM questions WHERE subject = ?``
然后对每题跑 ``difflib.SequenceMatcher``——题库越大、chunk 越多，开销
线性放大，且在 chunk 之间没有任何复用。

P2-4 的目标：在 chunked 路径下，由 orchestrator 在 chunk 循环外构造一次
``GlobalHashIndex.load(db, recent_days=...)``，整个 pipeline 共用同一张内
存索引；similarity_match 改为基于 ``question_hash`` 的严格命中，命中即
标记 `similarity_suggestion`，无需扫全表。

为了避免随历史题库爆炸，索引只加载最近 ``recent_days`` 内（默认 30）的
题目；若条数超过 ``HASH_INDEX_MAX_SIZE``（默认 50 万），降级为不在内存
建索引、每次走单条 SQL 查询，避免一次性吃掉大段内存。

env：
- ``HASH_INDEX_RECENT_DAYS``（默认 30，0 = 不限制）
- ``HASH_INDEX_MAX_SIZE``（默认 500_000）

接口（async）：
- ``load(db, *, recent_days=None, batch_id=None)``：从 DB 拉最近题目 +
  当前批次已写入的 import 记录建索引。
- ``lookup_question(subject, question_hash)``：返回 ``Question.id`` 或 None。
- ``lookup_import(subject, question_hash)``：返回 ``QuestionImport.id`` 或 None。
- ``add_import(subject, question_hash, import_id)``：写入 chunk 后调用，让
  后续 chunk 能跨 chunk 见到重号。

设计约束：
- 单 pass / 单 chunk / 无 db 路径**不**构造该索引，行为零变化。
- 失败降级（``_fallback_to_sql=True``）下 lookup 走单条 SQL，仍然正确。
- 内存里仅存 ``hash → id`` 的小整型 entry，单条不超过 ~80 字节，50 万条
  约 40 MB，在低配服务器上仍可控。
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utcnow

logger = logging.getLogger(__name__)


_DEFAULT_RECENT_DAYS = 30
_DEFAULT_MAX_SIZE = 500_000


def _resolve_recent_days(override: int | None) -> int:
    """0/负数表示不限时间窗口。"""
    if override is not None:
        return max(0, int(override))
    raw = os.environ.get("HASH_INDEX_RECENT_DAYS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_RECENT_DAYS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "Invalid HASH_INDEX_RECENT_DAYS=%r, using default %d",
            raw,
            _DEFAULT_RECENT_DAYS,
        )
        return _DEFAULT_RECENT_DAYS


def _resolve_max_size() -> int:
    raw = os.environ.get("HASH_INDEX_MAX_SIZE")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MAX_SIZE
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_MAX_SIZE
    except ValueError:
        logger.warning(
            "Invalid HASH_INDEX_MAX_SIZE=%r, using default %d", raw, _DEFAULT_MAX_SIZE
        )
        return _DEFAULT_MAX_SIZE


class GlobalHashIndex:
    """Subject + question_hash → existing id 索引。

    内存视图：``_question_index[(subject, hash)] = question_id``，
                ``_import_index[(subject, hash)] = import_id``。

    超阈值时 ``_fallback_to_sql=True``，两个 dict 留空，所有 lookup 都走
    单条 SQL（仍然正确，只是慢一点）。
    """

    def __init__(self) -> None:
        self._question_index: dict[tuple[str, str], int] = {}
        self._import_index: dict[tuple[str, str], int] = {}
        self._fallback_to_sql: bool = False
        self._loaded: bool = False
        self._recent_days: int = 0
        self._max_size: int = _DEFAULT_MAX_SIZE
        self._stats: dict[str, Any] = {
            "question_count": 0,
            "import_count": 0,
            "fallback_to_sql": False,
            "recent_days": 0,
        }

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def load(
        self,
        db: AsyncSession,
        *,
        recent_days: int | None = None,
        batch_id: str | None = None,
        batch_ids: list[str] | None = None,
    ) -> None:
        """从 DB 加载索引。

        - 计数 ``Question`` 表内最近 ``recent_days`` 内的活跃题目；
          超过 ``HASH_INDEX_MAX_SIZE`` 则进入 SQL fallback，**不**真正
          加载到内存。
        - 同时加载当前 ``batch_id`` 或 ``batch_ids`` 已写入的
          ``QuestionImport``（同批次内 chunk 间互查 / P2-5 resume 跨多个
          已成功 chunk 互查）。``batch_ids`` 优先于 ``batch_id``。
        """
        from app.models.admin import Subject
        from app.models.question import Question

        self._recent_days = _resolve_recent_days(recent_days)
        self._max_size = _resolve_max_size()
        self._stats["recent_days"] = self._recent_days

        question_filter = [
            Question.is_active == True,  # noqa: E712
            Question.question_hash.isnot(None),
        ]
        if self._recent_days > 0:
            cutoff = utcnow() - timedelta(days=self._recent_days)
            question_filter.append(Question.created_at >= cutoff)

        # 阈值检查（只 count，不真的取行）。SQL fallback 下两个 index 都
        # 留空，lookup 自动走单条查询。
        from sqlalchemy import func as sa_func

        count_stmt = select(sa_func.count(Question.id)).where(*question_filter)
        count = (await db.execute(count_stmt)).scalar() or 0

        if count > self._max_size:
            self._fallback_to_sql = True
            self._stats["fallback_to_sql"] = True
            self._stats["question_count"] = count
            self._loaded = True
            logger.info(
                "GlobalHashIndex falling back to SQL (count=%d > max_size=%d)",
                count,
                self._max_size,
            )
            return

        rows = (
            await db.execute(
                select(Subject.code, Question.question_hash, Question.id)
                .where(*question_filter)
                .join(Subject, Question.subject_id == Subject.id)
            )
        ).all()
        for subject, qhash, qid in rows:
            if subject and qhash:
                self._question_index[(subject, qhash)] = qid
        self._stats["question_count"] = len(self._question_index)

        if batch_ids is not None:
            ids = [bid for bid in batch_ids if bid]
        elif batch_id:
            ids = [batch_id]
        else:
            ids = []

        if ids:
            from app.models.question_import import QuestionImport

            import_rows = (
                await db.execute(
                    select(
                        Subject.code,
                        QuestionImport.question_hash,
                        QuestionImport.id,
                    )
                    .where(
                        QuestionImport.batch_id.in_(ids),
                        QuestionImport.question_hash.isnot(None),
                        QuestionImport.status != "rejected",
                    )
                    .join(Subject, QuestionImport.subject_id == Subject.id)
                )
            ).all()
            for subject, qhash, iid in import_rows:
                if subject and qhash:
                    self._import_index[(subject, qhash)] = iid
            self._stats["import_count"] = len(self._import_index)

        self._loaded = True

    async def lookup_question(
        self,
        db: AsyncSession,
        subject: str | None,
        question_hash: str | None,
    ) -> int | None:
        """命中已发布题库。fallback 模式下走单条 SQL。"""
        if not subject or not question_hash:
            return None

        if not self._fallback_to_sql:
            return self._question_index.get((subject, question_hash))

        from app.models.question import Question
        from app.services.admin_subject_service import resolve_subject_id

        resolved = await resolve_subject_id(db, subject)
        if resolved is None:
            return None
        row = (
            await db.execute(
                select(Question.id).where(
                    Question.subject_id == resolved,
                    Question.question_hash == question_hash,
                    Question.is_active == True,  # noqa: E712
                )
            )
        ).first()
        return row[0] if row else None

    async def lookup_import(
        self,
        db: AsyncSession,
        subject: str | None,
        question_hash: str | None,
    ) -> int | None:
        """命中已写入但未审核通过的 import 记录（含 pending）。"""
        if not subject or not question_hash:
            return None

        if not self._fallback_to_sql:
            return self._import_index.get((subject, question_hash))

        from app.models.question_import import QuestionImport
        from app.services.admin_subject_service import resolve_subject_id

        resolved = await resolve_subject_id(db, subject)
        if resolved is None:
            return None
        row = (
            await db.execute(
                select(QuestionImport.id).where(
                    QuestionImport.subject_id == resolved,
                    QuestionImport.question_hash == question_hash,
                    QuestionImport.status != "rejected",
                )
            )
        ).first()
        return row[0] if row else None

    def add_import(
        self,
        subject: str | None,
        question_hash: str | None,
        import_id: int,
    ) -> None:
        """chunk 写入完成后调用，让后续 chunk 能跨 chunk 命中。"""
        if not subject or not question_hash or not import_id:
            return
        if self._fallback_to_sql:
            return
        self._import_index.setdefault((subject, question_hash), import_id)

    @property
    def stats(self) -> dict[str, Any]:
        """Diagnostics 用，不做防御拷贝（调用方只读）。"""
        return self._stats

    @property
    def is_fallback(self) -> bool:
        return self._fallback_to_sql

    @property
    def is_loaded(self) -> bool:
        return self._loaded

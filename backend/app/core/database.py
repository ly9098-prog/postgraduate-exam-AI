import logging
import time

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger("postgraduate-ai.database")

# Per-role connection pool configuration
_POOL_BY_ROLE = {
    "web": (settings.DB_POOL_SIZE_WEB, settings.DB_MAX_OVERFLOW_WEB),
    "worker": (settings.DB_POOL_SIZE_WORKER, settings.DB_MAX_OVERFLOW_WORKER),
    "scheduler": (settings.DB_POOL_SIZE_SCHEDULER, settings.DB_MAX_OVERFLOW_SCHEDULER),
    "all": (settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW),
}
_role = getattr(settings, "PROCESS_ROLE", "web")
_pool_size, _max_overflow = _POOL_BY_ROLE.get(_role, (settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW))

_connect_args = {}
_engine_kwargs: dict = {
    "echo": settings.SQL_ECHO,
    "hide_parameters": True,
    "pool_pre_ping": settings.DB_POOL_PRE_PING,
    "pool_recycle": settings.DB_POOL_RECYCLE,
}

if "sqlite" in settings.DATABASE_URL:
    _connect_args = {"check_same_thread": False}
else:
    _engine_kwargs["pool_size"] = _pool_size
    _engine_kwargs["max_overflow"] = _max_overflow
    _engine_kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT

logger.info(
    "DB pool configured: role=%s pool_size=%d max_overflow=%d total_connections=%d",
    _role, _pool_size, _max_overflow, _pool_size + _max_overflow,
)

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    **_engine_kwargs,
)

# ── Slow query logging ─────────────────────────────────────

_slow_query_logger = logging.getLogger("app.db.slow_query")

try:
    from app.core.log_context import log_event as _log_event
except ImportError:  # pragma: no cover
    _log_event = None

if settings.SLOW_QUERY_MS > 0:

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        start = getattr(context, "_query_start_time", None)
        if start is None:
            return
        duration_ms = (time.perf_counter() - start) * 1000
        if duration_ms >= settings.SLOW_QUERY_MS:
            compact_sql = " ".join(statement.split())
            if len(compact_sql) > 1200:
                compact_sql = compact_sql[:1200] + "..."
            if _log_event is not None:
                _log_event(
                    _slow_query_logger, "db.slow_query", "warning",
                    duration_ms=round(duration_ms, 1),
                    rowcount=getattr(cursor, "rowcount", None),
                    executemany=executemany,
                    sql_preview=compact_sql,
                )
            else:
                _slow_query_logger.warning(
                    "slow query duration_ms=%.1f rowcount=%s executemany=%s sql=%s",
                    duration_ms,
                    getattr(cursor, "rowcount", None),
                    executemany,
                    compact_sql,
                )

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def _repair_sqlite_admin_bigint_pk(conn):
    def repair(sync_conn):
        if sync_conn.dialect.name != "sqlite":
            return

        from app.models.admin import AuditLog, QuestionVersion

        model_tables = {
            "audit_logs": AuditLog.__table__,
            "question_versions": QuestionVersion.__table__,
        }
        inspector = inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())
        for table_name, table in model_tables.items():
            backup_table = f"{table_name}__old_pk"
            table_exists = table_name in existing_tables
            backup_exists = backup_table in existing_tables
            if not table_exists and not backup_exists:
                continue

            if table_exists:
                columns = inspector.get_columns(table_name)
                id_column = next((column for column in columns if column["name"] == "id"), None)
                if id_column is None or id_column["type"].__class__.__name__.upper() == "INTEGER":
                    continue
                if not backup_exists:
                    sync_conn.exec_driver_sql(f'ALTER TABLE "{table_name}" RENAME TO "{backup_table}"')
                    existing_tables.discard(table_name)
                    existing_tables.add(backup_table)
                    backup_exists = True

            if backup_exists:
                backup_indexes = inspect(sync_conn).get_indexes(backup_table)
                for index in backup_indexes:
                    index_name = index.get("name")
                    if index_name and not index_name.startswith("sqlite_autoindex_"):
                        sync_conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{index_name}"')

            table.create(sync_conn, checkfirst=True)
            if backup_exists:
                new_columns = {column["name"] for column in inspect(sync_conn).get_columns(table_name)}
                old_columns = {column["name"] for column in inspect(sync_conn).get_columns(backup_table)}
                common_columns = [column.name for column in table.columns if column.name in new_columns and column.name in old_columns]
                if common_columns:
                    quoted_columns = ", ".join(f'"{column}"' for column in common_columns)
                    sync_conn.exec_driver_sql(
                        f'INSERT OR IGNORE INTO "{table_name}" ({quoted_columns}) '
                        f'SELECT {quoted_columns} FROM "{backup_table}"'
                    )

    await conn.run_sync(repair)


async def _ensure_duplicate_check_columns(conn):
    def repair(sync_conn):
        inspector = inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())
        table_columns = {
            "questions": {
                "question_hash": "VARCHAR(32)",
            },
            "question_imports": {
                "question_hash": "VARCHAR(32)",
                "duplicate_status": "VARCHAR(32) NOT NULL DEFAULT 'normal'",
                "duplicate_of_question_id": "BIGINT",
                "duplicate_of_import_id": "BIGINT",
            },
        }
        table_indexes = {
            "questions": ["question_hash"],
            "question_imports": ["question_hash", "duplicate_status"],
        }
        for table_name, columns in table_columns.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name not in existing_columns:
                    sync_conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_type}'))
            existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
            for column_name in table_indexes.get(table_name, []):
                index_name = f"ix_{table_name}_{column_name}"
                if index_name not in existing_indexes:
                    sync_conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ("{column_name}")'))

    await conn.run_sync(repair)


async def _ensure_app_user_admin_bindings_table(conn):
    def repair(sync_conn):
        inspector = inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())
        if "app_user_admin_bindings" in existing_tables:
            return
        from app.models.app_user_admin_binding import AppUserAdminBinding

        AppUserAdminBinding.__table__.create(sync_conn, checkfirst=True)

    await conn.run_sync(repair)


async def _ensure_user_ban_columns(conn):
    def repair(sync_conn):
        inspector = inspect(sync_conn)
        if "users" not in set(inspector.get_table_names()):
            return

        existing_columns = {column["name"] for column in inspector.get_columns("users")}
        column_specs = {
            "is_banned": "BOOLEAN NOT NULL DEFAULT FALSE",
            "banned_reason": "VARCHAR(256)",
            "banned_at": "TIMESTAMP",
            "banned_by": "INTEGER",
        }
        for column_name, column_type in column_specs.items():
            if column_name not in existing_columns:
                sync_conn.execute(text(f'ALTER TABLE "users" ADD COLUMN "{column_name}" {column_type}'))

        existing_indexes = {index["name"] for index in inspector.get_indexes("users")}
        if "ix_users_is_banned" not in existing_indexes:
            sync_conn.execute(text('CREATE INDEX IF NOT EXISTS "ix_users_is_banned" ON "users" ("is_banned")'))

    await conn.run_sync(repair)


async def _ensure_user_deleted_column(conn):
    def repair(sync_conn):
        inspector = inspect(sync_conn)
        if "users" not in set(inspector.get_table_names()):
            return
        existing_columns = {column["name"] for column in inspector.get_columns("users")}
        if "deleted_at" not in existing_columns:
            sync_conn.execute(text('ALTER TABLE "users" ADD COLUMN "deleted_at" TIMESTAMP'))

    await conn.run_sync(repair)


async def _ensure_sync_columns(conn):
    def repair(sync_conn):
        inspector = inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())

        if "questions" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("questions")}
            if "sync_uuid" not in cols:
                sync_conn.execute(text('ALTER TABLE "questions" ADD COLUMN "sync_uuid" VARCHAR(36)'))
            if "sync_version" not in cols:
                sync_conn.execute(text('ALTER TABLE "questions" ADD COLUMN "sync_version" INTEGER NOT NULL DEFAULT 0'))
            indexes = {i["name"] for i in inspector.get_indexes("questions")}
            if "ix_questions_sync_uuid" not in indexes:
                sync_conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS "ix_questions_sync_uuid" ON "questions" ("sync_uuid")'))

        if "tags" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("tags")}
            if "sync_uuid" not in cols:
                sync_conn.execute(text('ALTER TABLE "tags" ADD COLUMN "sync_uuid" VARCHAR(36)'))
            indexes = {i["name"] for i in inspector.get_indexes("tags")}
            if "ix_tags_sync_uuid" not in indexes:
                sync_conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS "ix_tags_sync_uuid" ON "tags" ("sync_uuid")'))

    await conn.run_sync(repair)


async def _ensure_pomodoro_table(conn):
    def repair(sync_conn):
        from app.models.pomodoro import PomodoroSession

        inspector = inspect(sync_conn)
        if "pomodoro_sessions" not in set(inspector.get_table_names()):
            PomodoroSession.__table__.create(sync_conn, checkfirst=True)
            return

        # Development-only: add missing columns for schema drift
        import os
        if os.environ.get("APP_ENV") == "production" or detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            return

        existing = {c["name"] for c in inspector.get_columns("pomodoro_sessions")}
        migrations = {
            "subject_id": "ALTER TABLE pomodoro_sessions ADD COLUMN subject_id INTEGER",
            "paused_at": "ALTER TABLE pomodoro_sessions ADD COLUMN paused_at DATETIME",
            "total_paused_sec": "ALTER TABLE pomodoro_sessions ADD COLUMN total_paused_sec INTEGER DEFAULT 0",
        }
        for col, ddl in migrations.items():
            if col not in existing:
                sync_conn.exec_driver_sql(ddl)

    await conn.run_sync(repair)


async def _ensure_batch_job_tables(conn):
    def repair(sync_conn):
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        ImportBatchJob.__table__.create(sync_conn, checkfirst=True)
        ImportBatchJobItem.__table__.create(sync_conn, checkfirst=True)

    await conn.run_sync(repair)


async def _ensure_vector_schema(conn):
    """PostgreSQL-only: create pgvector extension + question_embeddings table.

    生产环境应使用 Alembic migration 管理 schema。
    此函数仅用于本地开发环境，且每个 DDL 使用独立 SAVEPOINT，
    避免 PostgreSQL 单条失败后事务进入 aborted 状态。
    """
    def repair(sync_conn):
        if sync_conn.dialect.name != "postgresql":
            return

        # 生产环境不做 runtime DDL，应使用 Alembic migration
        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            return

        dim = int(settings.EMBEDDING_DIM)

        # 1. pgvector extension（独立 savepoint）
        try:
            with sync_conn.begin_nested():
                sync_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            logger.warning("pgvector extension unavailable; skipping vector schema", exc_info=True)
            return

        # 2. question_embeddings 表
        try:
            with sync_conn.begin_nested():
                sync_conn.execute(text(f'''
                CREATE TABLE IF NOT EXISTS question_embeddings (
                    id BIGSERIAL PRIMARY KEY,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    subject VARCHAR(32) NOT NULL,
                    question_type VARCHAR(32) NOT NULL,
                    embedding_model VARCHAR(128) NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    content_hash VARCHAR(64) NOT NULL,
                    content_text TEXT NOT NULL,
                    embedding vector({dim}) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    embedded_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(question_id, embedding_model)
                )
                '''))
        except Exception:
            logger.warning("question_embeddings table creation failed", exc_info=True)
            return

        # 3. B-tree 索引
        for idx_sql in [
            'CREATE INDEX IF NOT EXISTS ix_question_embeddings_question_id ON question_embeddings(question_id)',
            'CREATE INDEX IF NOT EXISTS ix_question_embeddings_subject ON question_embeddings(subject)',
            'CREATE INDEX IF NOT EXISTS ix_question_embeddings_content_hash ON question_embeddings(content_hash)',
        ]:
            try:
                with sync_conn.begin_nested():
                    sync_conn.execute(text(idx_sql))
            except Exception:
                logger.warning("vector index creation failed: %s", idx_sql[:80], exc_info=True)

        # 4. HNSW 索引（可选，独立 savepoint）
        try:
            with sync_conn.begin_nested():
                sync_conn.execute(text('''
                CREATE INDEX IF NOT EXISTS ix_question_embeddings_embedding_hnsw
                ON question_embeddings
                USING hnsw (embedding vector_cosine_ops)
                '''))
        except Exception:
            logger.warning("pgvector hnsw index unavailable; continue without vector index", exc_info=True)

    await conn.run_sync(repair)


async def _repair_postgres_sequences(conn):
    """Sync PG sequences for tables that may have explicit-ID inserts (bootstrap, etc)."""
    def repair(sync_conn):
        if sync_conn.dialect.name != "postgresql":
            return
        # Tables whose sequences may be out of sync due to bootstrap explicit-ID inserts
        tables_with_sequences = ["audit_logs", "question_versions"]
        for table_name in tables_with_sequences:
            sync_conn.execute(
                text(
                    f"SELECT setval('{table_name}_id_seq', "
                    f"COALESCE((SELECT MAX(id) FROM {table_name}), 1))"
                )
            )
    await conn.run_sync(repair)


async def init_db():
    if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
        return

    from app.models.admin_vector_config import (
        AdminVectorConfig,  # noqa: F401 — Phase 5 vector config
    )
    from app.models.ai_feedback_log import AiFeedbackLog  # noqa: F401
    from app.models.formula import (  # noqa: F401
        FormulaCard,
        FormulaCardTag,
        FormulaCardVersion,
        FormulaCategory,
        FormulaGraphAsset,
        FormulaGraphPreview,
        FormulaGraphSpec,
        FormulaImportItem,
        FormulaImportJob,
        FormulaTag,
        UserFormulaFavorite,
    )
    from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401 — Phase 3
    from app.models.knowledge_point import KnowledgePoint  # noqa: F401
    from app.models.question_knowledge_point import QuestionKnowledgePoint  # noqa: F401
    from app.models.recommendation_experiment import (
        RecommendationExperiment,  # noqa: F401 — Phase 4
    )
    from app.models.recommendation_experiment_assignment import (
        RecommendationExperimentAssignment,  # noqa: F401 — Phase 4
    )
    from app.models.recommendation_log import RecommendationLog  # noqa: F401
    from app.models.recommendation_metrics_daily import (
        RecommendationMetricsDaily,  # noqa: F401 — Phase 4
    )
    from app.models.recommendation_strategy_config import (
        RecommendationStrategyConfig,  # noqa: F401 — Phase 4
    )
    from app.models.refresh_token import RefreshToken  # noqa: F401 — register model for create_all
    from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401

    async with engine.begin() as conn:
        await _repair_sqlite_admin_bigint_pk(conn)
        await conn.run_sync(Base.metadata.create_all)
        await _repair_postgres_sequences(conn)
        await _ensure_user_ban_columns(conn)
        await _ensure_user_deleted_column(conn)
        await _ensure_app_user_admin_bindings_table(conn)
        await _ensure_duplicate_check_columns(conn)
        await _ensure_sync_columns(conn)
        await _ensure_pomodoro_table(conn)
        await _ensure_batch_job_tables(conn)
        await _ensure_vector_schema(conn)

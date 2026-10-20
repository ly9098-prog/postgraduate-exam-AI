import logging
import threading
import time

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
from app.core.orm_base import Base

logger = logging.getLogger("postgraduate-ai.database")


def _async_database_url(url: str) -> str:
    """Return a SQLAlchemy URL usable by the async application engine.

    Alembic's CI jobs intentionally use the shorthand ``sqlite:///...`` URL,
    while the application engine requires an async driver.  Keep accepting the
    shorthand at the configuration boundary and select aiosqlite here.
    """
    if url.startswith("sqlite+pysqlite://"):
        return url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


# Per-role connection pool configuration
_POOL_BY_ROLE = {
    "web": (settings.DB_POOL_SIZE_WEB, settings.DB_MAX_OVERFLOW_WEB),
    "worker": (settings.DB_POOL_SIZE_WORKER, settings.DB_MAX_OVERFLOW_WORKER),
    "scheduler": (settings.DB_POOL_SIZE_SCHEDULER, settings.DB_MAX_OVERFLOW_SCHEDULER),
    "all": (settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW),
}
_role = getattr(settings, "PROCESS_ROLE", "web")
_pool_size, _max_overflow = _POOL_BY_ROLE.get(
    _role, (settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW)
)

_connect_args = {}
_engine_kwargs: dict = {
    "echo": settings.SQL_ECHO,
    "hide_parameters": True,
    "pool_pre_ping": settings.DB_POOL_PRE_PING,
    "pool_recycle": settings.DB_POOL_RECYCLE,
}

_database_url = _async_database_url(settings.DATABASE_URL)

if "sqlite" in _database_url:
    _connect_args = {"check_same_thread": False}
else:
    # Production uses PostgreSQL+asyncpg.  DateTime columns intentionally store
    # naive UTC, while many models rely on server_default=func.now().  Pin the
    # PostgreSQL session timezone to UTC so CURRENT_TIMESTAMP cannot silently
    # become a local wall-clock value when the DB host/session timezone differs.
    if "postgresql+asyncpg" in _database_url:
        _connect_args = {"server_settings": {"timezone": "UTC"}}
    _engine_kwargs["pool_size"] = _pool_size
    _engine_kwargs["max_overflow"] = _max_overflow
    _engine_kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT

engine = create_async_engine(
    _database_url,
    connect_args=_connect_args,
    **_engine_kwargs,
)

# ── SQLite foreign key enforcement ─────────────────────────
# SQLite defaults PRAGMA foreign_keys to OFF per connection.  Enable it on every
# new connection so DB-level FK constraints (subject_id -> subjects.id, etc.)
# are actually enforced, not just declared.
if "sqlite" in _database_url:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

# ── Query performance metrics / slow query logging ─────────

_slow_query_logger = logging.getLogger("app.db.slow_query")
_query_metrics_lock = threading.Lock()
_query_metrics: dict[str, int | float] = {
    "total": 0,
    "slow": 0,
    "duration_ms_total": 0.0,
    "duration_ms_max": 0.0,
}


def get_db_query_metrics() -> dict[str, int | float]:
    """Return process-local DB execution metrics for Prometheus/health output."""
    with _query_metrics_lock:
        metrics = dict(_query_metrics)
    total = max(1, int(metrics["total"]))
    metrics["duration_ms_avg"] = float(metrics["duration_ms_total"]) / total
    return metrics


try:
    from app.core.log_context import log_event as _log_event
except ImportError:  # pragma: no cover
    _log_event = None


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = getattr(context, "_query_start_time", None)
    if start is None:
        return
    duration_ms = (time.perf_counter() - start) * 1000
    with _query_metrics_lock:
        _query_metrics["total"] = int(_query_metrics["total"]) + 1
        _query_metrics["duration_ms_total"] = (
            float(_query_metrics["duration_ms_total"]) + duration_ms
        )
        _query_metrics["duration_ms_max"] = max(
            float(_query_metrics["duration_ms_max"]), duration_ms
        )
        is_slow = settings.SLOW_QUERY_MS > 0 and duration_ms >= settings.SLOW_QUERY_MS
        if is_slow:
            _query_metrics["slow"] = int(_query_metrics["slow"]) + 1

    if not is_slow:
        return
    compact_sql = " ".join(statement.split())
    if len(compact_sql) > 1200:
        compact_sql = compact_sql[:1200] + "..."
    if _log_event is not None:
        _log_event(
            _slow_query_logger,
            "db.slow_query",
            "warning",
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
                id_column = next(
                    (column for column in columns if column["name"] == "id"), None
                )
                if (
                    id_column is None
                    or id_column["type"].__class__.__name__.upper() == "INTEGER"
                ):
                    continue
                if not backup_exists:
                    sync_conn.exec_driver_sql(
                        f'ALTER TABLE "{table_name}" RENAME TO "{backup_table}"'
                    )
                    existing_tables.discard(table_name)
                    existing_tables.add(backup_table)
                    backup_exists = True

            if backup_exists:
                backup_indexes = inspect(sync_conn).get_indexes(backup_table)
                for index in backup_indexes:
                    index_name = index.get("name")
                    if index_name and not index_name.startswith("sqlite_autoindex_"):
                        sync_conn.exec_driver_sql(
                            f'DROP INDEX IF EXISTS "{index_name}"'
                        )

            table.create(sync_conn, checkfirst=True)
            if backup_exists:
                new_columns = {
                    column["name"]
                    for column in inspect(sync_conn).get_columns(table_name)
                }
                old_columns = {
                    column["name"]
                    for column in inspect(sync_conn).get_columns(backup_table)
                }
                common_columns = [
                    column.name
                    for column in table.columns
                    if column.name in new_columns and column.name in old_columns
                ]
                if common_columns:
                    quoted_columns = ", ".join(
                        f'"{column}"' for column in common_columns
                    )
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
            existing_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            for column_name, column_type in columns.items():
                if column_name not in existing_columns:
                    sync_conn.execute(
                        text(
                            f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_type}'
                        )
                    )
            existing_indexes = {
                index["name"] for index in inspector.get_indexes(table_name)
            }
            for column_name in table_indexes.get(table_name, []):
                index_name = f"ix_{table_name}_{column_name}"
                if index_name not in existing_indexes:
                    sync_conn.execute(
                        text(
                            f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ("{column_name}")'
                        )
                    )

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
                sync_conn.execute(
                    text(
                        f'ALTER TABLE "users" ADD COLUMN "{column_name}" {column_type}'
                    )
                )

        existing_indexes = {index["name"] for index in inspector.get_indexes("users")}
        if "ix_users_is_banned" not in existing_indexes:
            sync_conn.execute(
                text(
                    'CREATE INDEX IF NOT EXISTS "ix_users_is_banned" ON "users" ("is_banned")'
                )
            )

    await conn.run_sync(repair)


async def _ensure_user_deleted_column(conn):
    def repair(sync_conn):
        inspector = inspect(sync_conn)
        if "users" not in set(inspector.get_table_names()):
            return
        existing_columns = {column["name"] for column in inspector.get_columns("users")}
        if "deleted_at" not in existing_columns:
            sync_conn.execute(
                text('ALTER TABLE "users" ADD COLUMN "deleted_at" TIMESTAMP')
            )

    await conn.run_sync(repair)


async def _ensure_sync_columns(conn):
    def repair(sync_conn):
        inspector = inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())

        if "questions" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("questions")}
            if "sync_uuid" not in cols:
                sync_conn.execute(
                    text('ALTER TABLE "questions" ADD COLUMN "sync_uuid" VARCHAR(36)')
                )
            if "sync_version" not in cols:
                sync_conn.execute(
                    text(
                        'ALTER TABLE "questions" ADD COLUMN "sync_version" INTEGER NOT NULL DEFAULT 0'
                    )
                )
            indexes = {i["name"] for i in inspector.get_indexes("questions")}
            if "ix_questions_sync_uuid" not in indexes:
                sync_conn.execute(
                    text(
                        'CREATE UNIQUE INDEX IF NOT EXISTS "ix_questions_sync_uuid" ON "questions" ("sync_uuid")'
                    )
                )

        if "tags" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("tags")}
            if "sync_uuid" not in cols:
                sync_conn.execute(
                    text('ALTER TABLE "tags" ADD COLUMN "sync_uuid" VARCHAR(36)')
                )
            indexes = {i["name"] for i in inspector.get_indexes("tags")}
            if "ix_tags_sync_uuid" not in indexes:
                sync_conn.execute(
                    text(
                        'CREATE UNIQUE INDEX IF NOT EXISTS "ix_tags_sync_uuid" ON "tags" ("sync_uuid")'
                    )
                )

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

        if (
            os.environ.get("APP_ENV") == "production"
            or detect_deployment_profile() == DeploymentProfile.CLOUD_API
        ):
            return

        existing = {c["name"] for c in inspector.get_columns("pomodoro_sessions")}
        migrations = {
            "paused_at": "ALTER TABLE pomodoro_sessions ADD COLUMN paused_at DATETIME",
            "total_paused_sec": "ALTER TABLE pomodoro_sessions ADD COLUMN total_paused_sec INTEGER DEFAULT 0",
        }
        for col, ddl in migrations.items():
            if col not in existing:
                sync_conn.exec_driver_sql(ddl)
        # subject_id is owned by Alembic (a7b8c9d0e1f2).  Never repair it at
        # startup — a missing column means migrations have not been applied.
        if "subject_id" not in existing:
            logger.error(
                "pomodoro_sessions.subject_id is missing — run `alembic upgrade head` "
                "(runtime schema repair for subject_id is disabled)"
            )

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

        # 已存在 DB-first 配置时以其维度建表，避免管理端配置与
        # settings.EMBEDDING_DIM 不一致而创建出不可查询的 vector 列。
        dim = int(settings.EMBEDDING_DIM)
        try:
            inspector = inspect(sync_conn)
            if "admin_vector_configs" in set(inspector.get_table_names()):
                configured_dim = sync_conn.execute(
                    text(
                        "SELECT embedding_dim FROM admin_vector_configs "
                        "ORDER BY id ASC LIMIT 1"
                    )
                ).scalar()
                if configured_dim:
                    dim = int(configured_dim)
        except Exception:
            logger.warning(
                "failed to resolve DB embedding dimension; using settings value %d",
                dim,
                exc_info=True,
            )

        # 1. pgvector extension（独立 savepoint）
        try:
            with sync_conn.begin_nested():
                sync_conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            logger.warning(
                "pgvector extension unavailable; skipping vector schema", exc_info=True
            )
            return

        # 2. question_embeddings 表
        try:
            with sync_conn.begin_nested():
                sync_conn.execute(
                    text(f"""
                CREATE TABLE IF NOT EXISTS question_embeddings (
                    id BIGSERIAL PRIMARY KEY,
                    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
                    subject_id INTEGER NOT NULL REFERENCES subjects(id),
                    question_type VARCHAR(32) NOT NULL,
                    model_id INTEGER NOT NULL REFERENCES admin_ai_model_configs(id),
                    embedding_dim INTEGER NOT NULL,
                    content_hash VARCHAR(64) NOT NULL,
                    content_text TEXT NOT NULL,
                    embedding vector({dim}) NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    embedded_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE(question_id, model_id)
                )
                """)
                )
        except Exception:
            logger.warning("question_embeddings table creation failed", exc_info=True)
            return

        # CREATE TABLE IF NOT EXISTS 不会修复已有列的维度；显式检查并告警，
        # 由迁移脚本处理，禁止在启动阶段隐式丢弃已有 embedding。
        try:
            type_name = sync_conn.execute(
                text("""
                SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema()
                  AND c.relname = 'question_embeddings'
                  AND a.attname = 'embedding'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                LIMIT 1
            """)
            ).scalar()
            expected_type = f"vector({dim})"
            if type_name != expected_type:
                logger.error(
                    "question_embeddings.embedding type mismatch: "
                    "expected=%s actual=%s; vector retrieval will stay disabled",
                    expected_type,
                    type_name,
                )
                return
        except Exception:
            logger.warning(
                "failed to verify question_embeddings vector dimension",
                exc_info=True,
            )
            return

        # 3. B-tree 索引
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS ix_question_embeddings_question_id ON question_embeddings(question_id)",
            "CREATE INDEX IF NOT EXISTS ix_question_embeddings_subject_id ON question_embeddings(subject_id)",
            "CREATE INDEX IF NOT EXISTS ix_question_embeddings_content_hash ON question_embeddings(content_hash)",
            "CREATE INDEX IF NOT EXISTS ix_question_embeddings_model_id ON question_embeddings(model_id)",
        ]:
            try:
                with sync_conn.begin_nested():
                    sync_conn.execute(text(idx_sql))
            except Exception:
                logger.warning(
                    "vector index creation failed: %s", idx_sql[:80], exc_info=True
                )

        # 4. HNSW 索引（可选，独立 savepoint）
        try:
            with sync_conn.begin_nested():
                sync_conn.execute(
                    text("""
                CREATE INDEX IF NOT EXISTS ix_question_embeddings_embedding_hnsw
                ON question_embeddings
                USING hnsw (embedding vector_cosine_ops)
                """)
                )
        except Exception:
            logger.warning(
                "pgvector hnsw index unavailable; continue without vector index",
                exc_info=True,
            )

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

    import app.models  # noqa: F401 — canonical complete model registry

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

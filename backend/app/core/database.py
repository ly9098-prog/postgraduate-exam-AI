from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

_connect_args = {}
_engine_kwargs: dict = {
    "echo": settings.APP_ENV == "development",
    "pool_recycle": settings.DB_POOL_RECYCLE,
}

if "sqlite" in settings.DATABASE_URL:
    _connect_args = {"check_same_thread": False}
else:
    _engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    **_engine_kwargs,
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


async def init_db():
    async with engine.begin() as conn:
        await _repair_sqlite_admin_bigint_pk(conn)
        await conn.run_sync(Base.metadata.create_all)

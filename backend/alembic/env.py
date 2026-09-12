import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.database import Base

# 导入所有 model 以便 autogenerate 检测变更（副作用导入，勿删）
from app.models.admin import (  # noqa: F401
    AdminUser,
    AuditLog,
    Permission,
    QuestionVersion,
    Role,
    RolePermission,
    Subject,
)
from app.models.admin_ai_config import AdminAiConfig, AdminAiModelConfig  # noqa: F401
from app.models.ai_chat import AiChat  # noqa: F401
from app.models.ai_generation_log import AiGenerationLog  # noqa: F401
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.error_diagnosis import WrongQuestionErrorDiagnosis  # noqa: F401
from app.models.exam import (  # noqa: F401
    ExamAnswer,
    ExamAttempt,
    ExamPaper,
    ExamPaperQuestion,
)
from app.models.export_task import ExportSnapshot, ExportTask  # noqa: F401
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
from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem  # noqa: F401
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk  # noqa: F401
from app.models.ocr_job import OCRJob  # noqa: F401
from app.models.pomodoro import (  # noqa: F401
    PomodoroPauseInterval,
    PomodoroSession,
    UserPomodoroSettings,
)
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.practice_session import PracticeSession  # noqa: F401
from app.models.question import Question  # noqa: F401
from app.models.question_import import QuestionImport  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.review_scheduler import ReviewRecord, ReviewSchedule  # noqa: F401
from app.models.sequential_reservation import SequentialReservation  # noqa: F401
from app.models.study_plan import StudyPlan, StudyPlanDay  # noqa: F401
from app.models.syllabus import (  # noqa: F401
    SyllabusKnowledgePoint,
    SyllabusKnowledgePointMapping,
    SyllabusVersion,
)
from app.models.user import User  # noqa: F401
from app.models.worker_credential import WorkerCredential  # noqa: F401
from app.models.wrong_question import WrongQuestion  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    import os
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    return config.get_main_option("sqlalchemy.url")


def _async_database_url(url: str) -> str:
    """Use an async driver when Alembic is running through the async env."""
    if url.startswith("sqlite+pysqlite://"):
        return url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


def run_migrations_offline() -> None:
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        _async_database_url(_get_database_url()),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

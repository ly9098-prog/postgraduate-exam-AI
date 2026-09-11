import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base

# 导入所有 model 以便 autogenerate 检测变更
from app.models.user import User
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.sequential_reservation import SequentialReservation  # noqa: F401
from app.models.wrong_question import WrongQuestion
from app.models.error_diagnosis import WrongQuestionErrorDiagnosis
from app.models.answer_behavior import AnswerBehavior
from app.models.exam import ExamAnswer, ExamAttempt, ExamPaper, ExamPaperQuestion
from app.models.ai_chat import AiChat
from app.models.tag import Tag
from app.models.ai_generation_log import AiGenerationLog
from app.models.review_scheduler import ReviewRecord, ReviewSchedule
from app.models.admin import AdminUser, AuditLog, Permission, QuestionVersion, Role, RolePermission, Subject
from app.models.watermark_rule import WatermarkRule
from app.models.admin_ai_config import AdminAiModelConfig, AdminAiConfig
from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk
from app.models.pomodoro import PomodoroPauseInterval, PomodoroSession, UserPomodoroSettings  # noqa: F401
from app.models.refresh_token import RefreshToken
from app.models.syllabus import SyllabusKnowledgePoint, SyllabusKnowledgePointMapping, SyllabusVersion  # noqa: F401
from app.models.study_plan import StudyPlan, StudyPlanDay  # noqa: F401
from app.models.ocr_job import OCRJob
from app.models.export_task import ExportTask, ExportSnapshot  # noqa: F401
from app.models.worker_credential import WorkerCredential
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
        _get_database_url(),
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

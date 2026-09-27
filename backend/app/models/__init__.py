# ruff: noqa: I001
"""Canonical SQLAlchemy model registry.

Import this package before using ``Base.metadata``.  Alembic and local database
initialization both rely on this module so their table registries cannot drift.
"""

# Import order matters: QuestionImport must be loaded before Subject because
# Subject.question_imports references "QuestionImport" by string name.
from app.models.question_import import QuestionImport  # noqa: F401
from app.models.admin import (  # noqa: F401
    AdminAISettings,
    AdminAIUsageMonthly,
    AdminUser,
    AuditLog,
    Permission,
    QuestionVersion,
    QuestionVersionKnowledgePoint,
    Role,
    RolePermission,
    Subject,
)
from app.models.admin_ai_config import AdminAiConfig, AdminAiModelConfig  # noqa: F401
from app.models.ai_chat import AiChat  # noqa: F401
from app.models.ai_feedback_log import AiFeedbackLog  # noqa: F401
from app.models.ai_generation_log import AiGenerationLog  # noqa: F401
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.app_user_admin_binding import AppUserAdminBinding  # noqa: F401
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
from app.models.import_batch_job import (  # noqa: F401
    BatchJobTraceEvent,
    ImportBatchJob,
    ImportBatchJobItem,
)
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk  # noqa: F401
from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.ocr_job import OCRJob  # noqa: F401
from app.models.pomodoro import (  # noqa: F401
    PomodoroPauseInterval,
    PomodoroSession,
    UserPomodoroSettings,
)
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.practice_session import PracticeSession  # noqa: F401
from app.models.question import Question  # noqa: F401
from app.models.question_knowledge_point import QuestionKnowledgePoint  # noqa: F401
from app.models.recommendation_experiment import RecommendationExperiment  # noqa: F401
from app.models.recommendation_experiment_assignment import (  # noqa: F401
    RecommendationExperimentAssignment,
)
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily  # noqa: F401
from app.models.recommendation_strategy_config import (  # noqa: F401
    RecommendationStrategyConfig,
)
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.review_scheduler import (  # noqa: F401
    ReviewRecord,
    ReviewSchedule,
    ReviewSession,
)
from app.models.sequential_reservation import SequentialReservation  # noqa: F401
from app.models.study_plan import StudyPlan, StudyPlanDay  # noqa: F401
from app.models.syllabus import (  # noqa: F401
    SyllabusKnowledgePoint,
    SyllabusKnowledgePointMapping,
    SyllabusVersion,
)
from app.models.tag import Tag  # noqa: F401
from app.models.task_outbox import TaskOutbox  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.user_adaptive_profile import UserAdaptiveProfile  # noqa: F401
from app.models.user_knowledge_adaptive_state import (  # noqa: F401
    UserKnowledgeAdaptiveState,
)
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401
from app.models.user_question_difficulty_state import (  # noqa: F401
    UserQuestionDifficultyState,
)
from app.models.user_question_state import UserQuestionState  # noqa: F401
from app.models.user_recommend_preference import UserRecommendPreference  # noqa: F401
from app.models.watermark_rule import WatermarkRule  # noqa: F401
from app.models.worker_credential import WorkerCredential  # noqa: F401
from app.models.wrong_question import WrongQuestion  # noqa: F401

# Apply legacy-compatible names and register intentionally retained performance
# indexes after every table has been loaded.
from app.models.schema_contract import register_schema_contract

register_schema_contract()
del register_schema_contract

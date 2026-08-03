# Import all models so SQLAlchemy can resolve string-based relationships.
# Order matters: QuestionImport must be loaded before Subject
# (Subject.question_imports references "QuestionImport" by string name).
from app.models.admin import AdminAISettings, AdminUser, Subject  # noqa: F401
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.formula import (  # noqa: F401
    FormulaCard,
    FormulaCardTag,
    FormulaCardVersion,
    FormulaCategory,
    FormulaGraphAsset,
    FormulaImportItem,
    FormulaImportJob,
    FormulaTag,
    UserFormulaFavorite,
)
from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem  # noqa: F401
from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.ocr_job import OCRJob  # noqa: F401
from app.models.pomodoro import PomodoroSession  # noqa: F401
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.question import Question  # noqa: F401
from app.models.question_import import QuestionImport  # noqa: F401
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import RecommendationMetricsDaily  # noqa: F401
from app.models.review_scheduler import ReviewRecord, ReviewSchedule  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.task_outbox import TaskOutbox  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401
from app.models.user_question_state import UserQuestionState  # noqa: F401
from app.models.worker_credential import WorkerCredential  # noqa: F401

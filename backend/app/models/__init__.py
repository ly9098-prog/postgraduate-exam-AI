# Import all models so SQLAlchemy can resolve string-based relationships.
# Order matters: QuestionImport must be loaded before Subject
# (Subject.question_imports references "QuestionImport" by string name).
from app.models.admin import AdminAISettings, AdminUser, Subject  # noqa: F401
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.error_diagnosis import WrongQuestionErrorDiagnosis  # noqa: F401
from app.models.exam import (  # noqa: F401
    ExamAnswer,
    ExamAttempt,
    ExamPaper,
    ExamPaperQuestion,
)
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
from app.models.pomodoro import (  # noqa: F401
    PomodoroPauseInterval,
    PomodoroSession,
    UserPomodoroSettings,
)
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.practice_session import PracticeSession  # noqa: F401
from app.models.sequential_reservation import SequentialReservation  # noqa: F401
from app.models.question import Question  # noqa: F401
from app.models.question_import import QuestionImport  # noqa: F401
from app.models.question_knowledge_point import QuestionKnowledgePoint  # noqa: F401
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import (
    RecommendationMetricsDaily,  # noqa: F401
)
from app.models.review_scheduler import ReviewRecord, ReviewSchedule  # noqa: F401
from app.models.study_plan import StudyPlan, StudyPlanDay  # noqa: F401
from app.models.syllabus import (  # noqa: F401
    SyllabusKnowledgePoint,
    SyllabusKnowledgePointMapping,
    SyllabusVersion,
)
from app.models.tag import Tag  # noqa: F401
from app.models.task_outbox import TaskOutbox  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401
from app.models.user_question_state import UserQuestionState  # noqa: F401
from app.models.worker_credential import WorkerCredential  # noqa: F401
from app.models.wrong_question import WrongQuestion  # noqa: F401

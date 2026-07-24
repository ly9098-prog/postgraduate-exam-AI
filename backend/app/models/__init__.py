# Import all models so SQLAlchemy can resolve string-based relationships.
# Order matters: QuestionImport must be loaded before Subject
# (Subject.question_imports references "QuestionImport" by string name).
from app.models.admin import AdminAISettings, AdminUser, Subject  # noqa: F401
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
from app.models.ocr_job import OCRJob  # noqa: F401
from app.models.question import Question  # noqa: F401
from app.models.question_import import QuestionImport  # noqa: F401
from app.models.user_question_state import UserQuestionState  # noqa: F401
from app.models.worker_credential import WorkerCredential  # noqa: F401

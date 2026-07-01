# Import all models so SQLAlchemy can resolve string-based relationships.
# Order matters: QuestionImport must be loaded before Subject
# (Subject.question_imports references "QuestionImport" by string name).
from app.models.question_import import QuestionImport  # noqa: F401
from app.models.admin import Subject, AdminUser, AdminAISettings  # noqa: F401
from app.models.question import Question  # noqa: F401
from app.models.user_question_state import UserQuestionState  # noqa: F401

from sqlalchemy.dialects import postgresql

from app.models.error_diagnosis import WrongQuestionErrorDiagnosis
from app.services.error_diagnosis_service import _effective_type_count_stmt


def test_effective_type_count_uses_labeled_subquery_for_postgres_grouping():
    stmt = _effective_type_count_stmt([
        WrongQuestionErrorDiagnosis.user_id == 7,
    ])
    sql = str(stmt.compile(dialect=postgresql.dialect()))

    # The outer GROUP BY must reference the projected alias instead of rebuilding
    # the CASE expression with a second set of bind parameters.
    assert "GROUP BY anon_1.effective_type" in sql
    assert sql.count("CASE WHEN") == 1

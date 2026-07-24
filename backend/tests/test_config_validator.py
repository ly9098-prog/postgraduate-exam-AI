"""Tests for production config validator (P0-7, P1-6 checks)."""

from app.services.production_config_validator import (
    _check_db_pool_budget,
)


class TestDbPoolBudget:
    """DB_POOL_SIZE * workers must not exceed MAX_CONNECTIONS."""

    def test_normal_budget_passes(self):
        errors = []
        _check_db_pool_budget(errors)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

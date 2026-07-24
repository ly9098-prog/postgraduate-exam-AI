"""Tests for production config validator (P0-7, P1-6 checks)."""

import pytest
from unittest.mock import patch, MagicMock
from app.services.production_config_validator import (
    _check_db_pool_budget,
    _check_queue_capacity,
)


class TestDbPoolBudget:
    """DB_POOL_SIZE * workers must not exceed MAX_CONNECTIONS."""

    def test_normal_budget_passes(self):
        errors = []
        _check_db_pool_budget(errors)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"


class TestQueueCapacity:
    """MAX_QUEUE_SIZE and MAX_DEAD_SIZE must be reasonable."""

    def test_queue_capacity_reasonable(self):
        errors = []
        _check_queue_capacity(errors)
        assert len(errors) == 0, f"Expected no errors, got: {errors}"

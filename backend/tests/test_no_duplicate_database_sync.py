"""Tests confirming no duplicate database sync coordinator exists."""

import pytest


class TestNoDuplicateDatabaseSync:
    """Ensure no SyncCoordinator class exists in app.features."""

    def test_no_new_sync_class(self):
        """There is no 'SyncCoordinator' in the app.features package."""
        import app.features
        assert not hasattr(app.features, "SyncCoordinator"), \
            "SyncCoordinator should not exist — merge_sync_service handles sync"

    def test_existing_sync_importable(self):
        """merge_sync_service is importable and provides merge_sync_package."""
        from app.features.sync_merge_service import merge_sync_package
        assert callable(merge_sync_package)

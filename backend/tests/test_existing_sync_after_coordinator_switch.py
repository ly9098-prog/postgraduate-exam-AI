"""Sprint 4C: Verify sync service remains functional after coordinator switch.

The sync import/merge service must remain importable and structurally intact
regardless of coordinator pipeline changes.
"""

from __future__ import annotations


class TestExistingSyncAfterCoordinatorSwitch:
    """Verify sync services are importable post-coordinator migration."""

    def test_sync_merge_service_importable(self):
        """merge_sync_package and SyncReport import from sync_merge_service."""
        from app.features.sync_merge_service import SyncReport, merge_sync_package

        assert callable(merge_sync_package)
        assert SyncReport is not None
        assert isinstance(SyncReport, type)

    def test_sync_merge_service_sync_report_fields(self):
        """SyncReport dataclass has expected fields."""
        from app.features.sync_merge_service import SyncReport

        report = SyncReport()
        assert hasattr(report, "questions_new")
        assert hasattr(report, "questions_updated")
        assert hasattr(report, "questions_skipped")
        assert hasattr(report, "questions_conflict")
        assert hasattr(report, "questions_deduped")
        assert hasattr(report, "tags_new")
        assert hasattr(report, "tags_skipped")
        assert hasattr(report, "conflicts")
        assert hasattr(report, "errors")

    def test_sync_api_importable(self):
        """import_sync_package is importable from api router."""
        from app.api.v1.sync import import_sync_package

        assert callable(import_sync_package)

    def test_sync_router_exists(self):
        """Sync API router is importable."""
        from app.api.v1.sync import router

        assert router is not None

    def test_sync_package_model(self):
        """SyncPackage pydantic model is importable with expected fields."""
        from app.schemas.sync import SyncPackage

        # Pydantic v2 compat
        try:
            fields = SyncPackage.model_fields
        except AttributeError:
            fields = SyncPackage.__fields__  # type: ignore[attr-defined]

        field_names = set(fields.keys())
        expected = {"version", "exported_at", "source_env", "questions", "tags", "manifest"}
        assert expected.issubset(field_names), (
            f"Missing fields: {expected - field_names}"
        )

    def test_sync_manifest_schema(self):
        """SyncManifest has expected fields."""
        from app.schemas.sync import SyncManifest

        try:
            fields = SyncManifest.model_fields
        except AttributeError:
            fields = SyncManifest.__fields__  # type: ignore[attr-defined]

        field_names = set(fields.keys())
        expected = {"question_count", "tag_count", "checksum"}
        assert expected.issubset(field_names), (
            f"Missing fields: {expected - field_names}"
        )

    def test_sync_report_response_schema(self):
        """SyncReportResponse has expected fields."""
        from app.schemas.sync import SyncReportResponse

        try:
            fields = SyncReportResponse.model_fields
        except AttributeError:
            fields = SyncReportResponse.__fields__  # type: ignore[attr-defined]

        field_names = set(fields.keys())
        expected = {
            "success", "questions_new", "questions_updated",
            "questions_skipped", "questions_conflict", "questions_deduped",
            "tags_new", "tags_skipped", "conflicts", "errors",
        }
        assert expected.issubset(field_names), (
            f"Missing fields: {expected - field_names}"
        )

    def test_sync_max_constants(self):
        """MAX_QUESTIONS_PER_SYNC and MAX_TAGS_PER_SYNC are defined."""
        from app.features.sync_merge_service import (
            MAX_QUESTIONS_PER_SYNC,
            MAX_TAGS_PER_SYNC,
        )

        assert isinstance(MAX_QUESTIONS_PER_SYNC, int)
        assert isinstance(MAX_TAGS_PER_SYNC, int)
        assert MAX_QUESTIONS_PER_SYNC > 0
        assert MAX_TAGS_PER_SYNC > 0

    def test_sync_package_instantiable(self):
        """SyncPackage can be instantiated with valid data."""
        from app.schemas.sync import SyncManifest, SyncPackage

        pkg = SyncPackage(
            version=1,
            exported_at="2025-01-01T00:00:00",
            source_env="local",
            questions=[],
            tags=[],
            manifest=SyncManifest(question_count=0, tag_count=0),
        )
        assert pkg.version == 1
        assert pkg.questions == []
        assert pkg.tags == []
        assert pkg.manifest.question_count == 0

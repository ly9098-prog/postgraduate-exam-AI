"""Production prewarm worker must see runtime-uploaded question images."""

from pathlib import Path


def test_prod_prewarm_worker_shares_question_assets_read_only():
    compose_path = Path(__file__).resolve().parents[3] / "deploy/docker-compose.prod.yml"
    compose = compose_path.read_text(encoding="utf-8")
    # Restrict the assertion to each service; a mount in app alone does not
    # make uploaded question images readable in the separate prewarm worker.
    app = compose.split("  app:\n", 1)[1].split("  worker:\n", 1)[0]
    worker = compose.split("  worker:\n", 1)[1].split("  admin:\n", 1)[0]
    assert "- question_assets_data:/app/static/question-assets\n" in app
    assert "- question_assets_data:/app/static/question-assets:ro\n" in worker

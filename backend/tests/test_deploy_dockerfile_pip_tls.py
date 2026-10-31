from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [
    ROOT / "Dockerfile",
    ROOT / "docker" / "Dockerfile",
    ROOT.parent / "deploy" / "Dockerfile.prod",
]


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.name)
def test_pip_keeps_tls_verification(path: Path):
    text = path.read_text(encoding="utf-8")
    assert "--trusted-host" not in text
    assert "http://mirrors" not in text
    assert "PIP_TRUSTED_HOST" not in text

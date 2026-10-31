import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _names(path: Path, pattern: str) -> set[str]:
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(pattern, line)
        if match:
            found.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return found


def test_production_image_installs_from_hashed_lock():
    text = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes" in text
    assert "requirements.lock" in text
    assert "-r requirements.txt" not in text


def test_lock_pins_every_direct_requirement_with_hashes():
    lock = ROOT / "requirements.lock"
    direct = _names(ROOT / "requirements.txt", r"([A-Za-z0-9_.-]+)")
    pinned = _names(lock, r"([A-Za-z0-9_.-]+)==")
    assert direct <= pinned, f"missing from lock: {sorted(direct - pinned)}"
    entries = len(re.findall(r"^[A-Za-z0-9_.-]+==", lock.read_text(), re.M))
    hashes = lock.read_text().count("--hash=sha256:")
    assert entries and hashes >= entries

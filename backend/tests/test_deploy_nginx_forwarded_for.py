from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = [
    ROOT / "deploy" / "nginx" / "nginx.conf",
    ROOT / "backend" / "docker" / "nginx.conf",
]


@pytest.mark.parametrize("path", NGINX_CONFIGS, ids=lambda p: str(p.relative_to(ROOT)))
def test_nginx_overwrites_forwarded_for_with_remote_addr(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = [
        line.strip()
        for line in text.splitlines()
        if "X-Forwarded-For" in line and not line.strip().startswith("#")
    ]
    assert lines, "no X-Forwarded-For directive found"
    assert "$proxy_add_x_forwarded_for" not in text
    assert all(line == "proxy_set_header X-Forwarded-For $remote_addr;" for line in lines)


def _location_blocks(text: str) -> list[str]:
    """Static check only: split on `location` and take each block up to its closing brace."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    blocks, current, depth = [], None, 0
    for ln in lines:
        s = ln.strip()
        if current is None and s.startswith("location "):
            current, depth = [], 0
        if current is not None:
            current.append(s)
            depth += s.count("{") - s.count("}")
            if depth <= 0 and "}" in s:
                blocks.append("\n".join(current))
                current = None
    return blocks


@pytest.mark.parametrize("path", NGINX_CONFIGS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_proxy_pass_location_sets_forwarded_for(path: Path):
    proxied = [b for b in _location_blocks(path.read_text(encoding="utf-8")) if "proxy_pass" in b]
    assert proxied
    for block in proxied:
        assert "proxy_set_header X-Forwarded-For $remote_addr;" in block, block

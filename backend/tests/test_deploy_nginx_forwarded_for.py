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


def test_nginx_adds_no_cache_for_admin_html_documents():
    """2026-11-07 admin 旧构建崩溃（BUGS_HISTORY 同日条目）的防回退守卫。

    Next 预渲染 HTML 自带 s-maxage 长缓存，浏览器启发式缓存 HTML 导致部署后
    旧标签页继续执行旧构建脚本（旧 chunk 已 404）。生产 nginx 必须按上游
    Content-Type 对文档类响应追加 no-cache，且该 add_header 必须留在 server
    级（location 级 add_header 会使 server 级安全头全部失效）。
    仅约束生产配置：backend/docker/nginx.conf 是纯后端 API 开发配置，
    不承载 admin 前端，无此问题。
    """
    text = (ROOT / "deploy" / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    assert "map $upstream_http_content_type $admin_doc_cache_control" in body
    # 文档类 Content-Type（带 charset 后缀，须前缀正则）映射为 no-cache
    assert '~*^text/html' in body and '"no-cache"' in body
    assert '~*^text/x-component' in body and '"no-cache"' in body
    # server 级下发（不在任何 location 块内）；空值不发头，chunk/API 响应不受影响
    assert "add_header Cache-Control $admin_doc_cache_control always;" in body
    location_blocks = _location_blocks(body)
    assert location_blocks, "no location blocks parsed"
    assert not any(
        "add_header Cache-Control $admin_doc_cache_control" in block
        for block in location_blocks
    )

#!/usr/bin/env python3
"""OCR Preflight Check — 发布前检查脚本。

离线检查（默认，无需后端服务）:
  1. Regression test files exist
  2. Acceptance case.json files exist
  3. OCR cache directory writable
  4. Pipeline artifact directory writable
  5. Scripts directory accessible

在线检查（需 --api-base-url）:
  6. Cleanup dry-run
  7. Vision model config exists
  8. DeepSeek API key configured

用法:
    # 离线检查
    python scripts/ocr_preflight_check.py

    # 详细输出
    python scripts/ocr_preflight_check.py --verbose

    # 包含在线检查
    python scripts/ocr_preflight_check.py --api-base-url http://localhost:8000/api/admin/v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _project_root() -> str:
    return os.path.dirname(_script_dir())


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_regression_test_files() -> dict:
    """Check that regression test case JSON files exist."""
    cases_dir = os.path.join(_project_root(), "tests", "ocr_regression", "cases")
    if not os.path.isdir(cases_dir):
        return {"name": "回归测试用例", "status": "warn", "detail": "cases 目录不存在"}

    files = [f for f in os.listdir(cases_dir) if f.endswith(".json")]
    if not files:
        return {"name": "回归测试用例", "status": "warn", "detail": "未找到 JSON case 文件，请确认已添加回归测试用例"}
    return {
        "name": "回归测试用例",
        "status": "pass",
        "detail": f"找到 {len(files)} 个用例: {', '.join(files[:5])}{'...' if len(files) > 5 else ''}",
    }


def check_acceptance_cases() -> dict:
    """Check that acceptance case.json files exist."""
    cases_dir = os.path.join(_project_root(), "tests", "ocr_acceptance", "cases")
    if not os.path.isdir(cases_dir):
        return {"name": "验收测试用例", "status": "warn", "detail": "cases 目录不存在"}

    case_names = []
    for entry in sorted(os.listdir(cases_dir)):
        sub = os.path.join(cases_dir, entry)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "case.json")):
            case_names.append(entry)

    if not case_names:
        return {"name": "验收测试用例", "status": "warn", "detail": "未找到 case 目录（需包含 case.json），请确认已添加验收用例"}
    return {
        "name": "验收测试用例",
        "status": "pass",
        "detail": f"找到 {len(case_names)} 个 case 模版: {', '.join(case_names[:5])}{'...' if len(case_names) > 5 else ''}",
    }


def check_ocr_cache_dir() -> dict:
    """Check OCR cache directory is writable."""
    cache_dir = os.environ.get(
        "OCR_CACHE_DIR",
        os.path.join(_project_root(), ".backend_cache", "ocr"),
    )

    if not os.path.isdir(cache_dir):
        try:
            os.makedirs(cache_dir, mode=0o755, exist_ok=True)
            return {"name": "OCR 缓存目录", "status": "pass", "detail": f"已创建: {cache_dir}"}
        except OSError as exc:
            return {"name": "OCR 缓存目录", "status": "fail", "detail": f"无法创建: {exc}"}

    if os.access(cache_dir, os.W_OK):
        return {"name": "OCR 缓存目录", "status": "pass", "detail": cache_dir}
    return {"name": "OCR 缓存目录", "status": "fail", "detail": f"目录不可写: {cache_dir}"}


def check_artifact_dir() -> dict:
    """Check pipeline artifact directory is writable."""
    artifact_dir = os.environ.get(
        "PIPELINE_ARTIFACT_DIR",
        os.path.join(_project_root(), ".backend_cache", "pipeline_artifacts"),
    )

    if not os.path.isdir(artifact_dir):
        try:
            os.makedirs(artifact_dir, mode=0o755, exist_ok=True)
            return {"name": "Pipeline Artifact 目录", "status": "pass", "detail": f"已创建: {artifact_dir}"}
        except OSError as exc:
            return {"name": "Pipeline Artifact 目录", "status": "fail", "detail": f"无法创建: {exc}"}

    if os.access(artifact_dir, os.W_OK):
        return {"name": "Pipeline Artifact 目录", "status": "pass", "detail": artifact_dir}
    return {"name": "Pipeline Artifact 目录", "status": "fail", "detail": f"目录不可写: {artifact_dir}"}


def check_scripts_dir() -> dict:
    """Check scripts directory is accessible."""
    scripts = os.path.join(_project_root(), "backend", "scripts")
    if os.path.isdir(scripts):
        return {"name": "后端脚本目录", "status": "pass", "detail": scripts}
    return {"name": "后端脚本目录", "status": "warn", "detail": f"目录不存在: {scripts}"}


# ---------------------------------------------------------------------------
# Online checks (require --api-base-url)
# ---------------------------------------------------------------------------


def check_config_via_api(api_base_url: str) -> list[dict]:
    """Run online configuration checks via API."""
    import urllib.request
    import urllib.error

    results: list[dict] = []

    # Check cleanup dry-run
    try:
        req = urllib.request.Request(
            f"{api_base_url}/imports/maintenance/cleanup",
            data=json.dumps({"target": "all", "dry_run": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            total_scanned = sum(
                t.get("scanned_count", 0) for t in data.get("targets", {}).values()
                if isinstance(t, dict)
            )
            results.append({
                "name": "Cleanup Dry-Run",
                "status": "pass",
                "detail": f"扫描完成，共 {total_scanned} 个可清理条目",
            })
    except urllib.error.HTTPError as exc:
        results.append({
            "name": "Cleanup Dry-Run",
            "status": "warn" if exc.code in (401, 403) else "fail",
            "detail": f"HTTP {exc.code}: {exc.reason}",
        })
    except Exception as exc:
        results.append({
            "name": "Cleanup Dry-Run",
            "status": "warn",
            "detail": f"后端不可达: {exc}",
        })

    # Check AI config (Vision + DeepSeek)
    try:
        req = urllib.request.Request(
            f"{api_base_url}/ai-settings/configs",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            configs = json.loads(resp.read().decode())
            vision_configured = bool(configs.get("configs", {}).get("vision_enabled"))
            deepseek_configured = bool(configs.get("configs", {}).get("deepseek_api_key"))

            results.append({
                "name": "Vision 模型配置",
                "status": "pass" if vision_configured else "warn",
                "detail": "已配置" if vision_configured else "未配置（如需图片导入请确认）",
            })
            results.append({
                "name": "DeepSeek API 配置",
                "status": "pass" if deepseek_configured else "warn",
                "detail": "已配置" if deepseek_configured else "未配置（AI 修复不可用）",
            })
    except urllib.error.HTTPError as exc:
        results.append({
            "name": "AI 配置检查",
            "status": "warn",
            "detail": f"HTTP {exc.code}: {exc.reason}",
        })
    except Exception as exc:
        results.append({
            "name": "AI 配置检查",
            "status": "warn",
            "detail": f"后端不可达: {exc}",
        })

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_checks(api_base_url: str | None = None, verbose: bool = False) -> dict:
    """Run all preflight checks and return results."""
    all_checks: list[dict] = []

    # Offline checks
    offline_checks = [
        check_regression_test_files(),
        check_acceptance_cases(),
        check_ocr_cache_dir(),
        check_artifact_dir(),
        check_scripts_dir(),
    ]
    all_checks.extend(offline_checks)

    # Online checks (if API base URL provided)
    if api_base_url:
        online_checks = check_config_via_api(api_base_url)
        all_checks.extend(online_checks)
    else:
        all_checks.append({
            "name": "在线检查",
            "status": "warn",
            "detail": "跳过（未提供 --api-base-url）",
        })

    # Determine overall status
    fail_count = sum(1 for c in all_checks if c["status"] == "fail")
    warn_count = sum(1 for c in all_checks if c["status"] == "warn")

    if fail_count > 0:
        overall = "fail"
    elif warn_count > 0:
        overall = "warn"
    else:
        overall = "pass"

    result: dict[str, Any] = {
        "status": overall,
        "checks": all_checks,
        "summary": {
            "total": len(all_checks),
            "pass": sum(1 for c in all_checks if c["status"] == "pass"),
            "warn": warn_count,
            "fail": fail_count,
        },
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OCR 导入发布前预检查脚本（离线优先）",
    )
    parser.add_argument(
        "--api-base-url",
        default=None,
        help="管理端 API 基础 URL，提供后启用在线检查",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出每个检查的详细信息",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出",
    )
    args = parser.parse_args()

    result = run_checks(
        api_base_url=args.api_base_url,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\nOCR Preflight Check — {'✅ PASS' if result['status'] == 'pass' else '⚠️  WARN' if result['status'] == 'warn' else '❌ FAIL'}")
        print(f"{'=' * 50}")
        summary = result["summary"]
        print(f"总计: {summary['total']} | ✅ {summary['pass']} | ⚠️  {summary['warn']} | ❌ {summary['fail']}\n")

        for check in result["checks"]:
            icon = {"pass": "✅", "warn": "⚠️ ", "fail": "❌"}.get(check["status"], "➖")
            print(f"  {icon} [{check['status'].upper()}] {check['name']}")
            if args.verbose and check.get("detail"):
                print(f"     {check['detail']}")

        print()

    if result["status"] == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Cloud Profile CUDA — Verify no CUDA initialization in cloud profile."""
from __future__ import annotations


def test_no_torch_cuda_at_top_level_imports():
    """Scan app/ (excluding tests, ocr_worker) for top-level torch.cuda imports."""
    import ast
    import os

    violations = []
    for root, dirs, files in os.walk("app"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "ocr_worker")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath) as f:
                    tree = ast.parse(f.read())
            except SyntaxError:
                continue

            in_function = 0
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    in_function += 1
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if "torch.cuda" in alias.name and in_function == 0:
                            violations.append(f"{fpath}: import {alias.name}")
            assert len(violations) == 0, f"Top-level torch.cuda imports found: {violations}"


def test_cloud_does_not_probe_cuda():
    """Verify cloud_api profile capabilities report no GPU."""
    from app.core.deployment_profile import DeploymentProfile
    from app.features.runtime_capabilities import build_runtime_capabilities

    caps = build_runtime_capabilities(DeploymentProfile.CLOUD_API)
    assert caps.gpu_available is False
    assert caps.gpu_memory_bytes is None

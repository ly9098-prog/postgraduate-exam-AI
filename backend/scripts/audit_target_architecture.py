#!/usr/bin/env python3
"""Architecture Gap Analysis — Sprint 4A Target vs. Current Implementation.

Generates:
  reports/sprint4a/current_to_target_map.json  — component-level mapping
  reports/sprint4a/current_to_target_map.md    — human-readable mapping
  reports/sprint4a/call_graph.json              — known call points
  reports/sprint4a/architecture_gaps.json       — gap classification

Invocation:
  PYTHONPATH=. python scripts/audit_target_architecture.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FEATURES = REPO / "app" / "features"
CORE = REPO / "app" / "core"
SERVICES = REPO / "app" / "services"
OCR_WORKER = REPO / "app" / "ocr_worker"
TESTS = REPO / "tests"
OUT = REPO / "reports" / "sprint4a"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Target architecture components (from next_task.md)
# ---------------------------------------------------------------------------

TARGET_COMPONENTS: dict[str, dict[str, Any]] = {
    "ControlPlaneFacade": {
        "type": "coordinator",
        "inputs": ["ImportRequest", "PipelineExecutionContext"],
        "outputs": ["PipelineExecutionContext", "ExecutionPolicy", "QuotaLease"],
        "description": "Logical Control Plane — job creation/resume, quota, idempotency, rollout",
        "mode_switches": {"CONTROL_PLANE_MODE": ["legacy", "facade"]},
    },
    "PipelineExecutionContext": {
        "type": "dataclass",
        "inputs": [],
        "outputs": [],
        "description": "Unified context carrying pipeline_id, fingerprint, quota, feature flags, trace/metrics collectors",
        "mode_switches": {},
    },
    "InputGateway": {
        "type": "gateway",
        "inputs": ["ImportRequest"],
        "outputs": ["InputDocument"],
        "description": "Unified input entry — type detection, safety validation, file persistence",
        "mode_switches": {},
    },
    "InputSafetyValidator": {
        "type": "validator",
        "inputs": ["bytes", "InputDocument"],
        "outputs": ["SafetyResult"],
        "description": "File type/MIME consistency, magic bytes, size, compression bomb, encryption, path traversal",
        "mode_switches": {},
    },
    "NativeTextProbe": {
        "type": "probe",
        "inputs": ["InputDocument"],
        "outputs": ["NativeTextProbeResult"],
        "description": "Per-page text layer analysis with route recommendation",
        "mode_switches": {"NATIVE_TEXT_ROUTING_MODE": ["off", "shadow"]},
    },
    "PageRenderer": {
        "type": "renderer",
        "inputs": ["InputDocument"],
        "outputs": ["RenderedPage"],
        "description": "PDF page → image rendering with DPI control",
        "mode_switches": {},
    },
    "PageStream": {
        "type": "stream",
        "inputs": ["InputDocument", "PipelineExecutionContext"],
        "outputs": ["AsyncIterator[RenderedPage]"],
        "description": "Windowed page iteration with atomic disk persistence, resume, bounded memory",
        "mode_switches": {"PAGE_STREAM_MODE": ["legacy", "stream"]},
    },
    "OCRGateway": {
        "type": "gateway",
        "inputs": ["RenderedPage", "PipelineExecutionContext"],
        "outputs": ["ModuleResult[PageIR]"],
        "description": "Production OCR entry — capability routing, circuit breaker, quota, fallback",
        "mode_switches": {"OCR_GATEWAY_MODE": ["legacy", "shadow", "gateway"]},
    },
    "AdapterRegistry": {
        "type": "registry",
        "inputs": [],
        "outputs": ["list[OcrAdapter]", "list[DocumentTransformAdapter]"],
        "description": "Adapter registration and lookup (ALREADY EXISTS)",
        "mode_switches": {},
    },
    "AdapterSelector": {
        "type": "selector",
        "inputs": ["OCRRequest"],
        "outputs": ["OcrAdapter"],
        "description": "Capability/health/circuit-breaker aware adapter selection (ALREADY EXISTS)",
        "mode_switches": {},
    },
    "DocumentIR": {
        "type": "model",
        "inputs": [],
        "outputs": [],
        "description": "Canonical document intermediate representation (ALREADY EXISTS — full implementation)",
        "mode_switches": {"DOCUMENT_IR_SSOT_MODE": ["dual", "ir"]},
    },
    "ReadingOrderCoordinator": {
        "type": "coordinator",
        "inputs": ["DocumentIR"],
        "outputs": ["DocumentIR"],
        "description": "Reading order resolution for all pages (PARTIALLY EXISTS as reading_order.py + reading_order_stage.py)",
        "mode_switches": {},
    },
    "DomainParsingCoordinator": {
        "type": "coordinator",
        "inputs": ["DocumentIR"],
        "outputs": ["list[NormalizedQuestion]"],
        "description": "Question/option/answer parsing, cross-page linking, compound structure (PARTIALLY EXISTS)",
        "mode_switches": {},
    },
    "CorrectionCoordinator": {
        "type": "coordinator",
        "inputs": ["DocumentIR", "list[NormalizedQuestion]"],
        "outputs": ["list[CorrectionCandidate]"],
        "description": "OCR correction, AI repair, rule fallback coordination (PARTIALLY EXISTS)",
        "mode_switches": {},
    },
    "UnifiedSafetyEvaluator": {
        "type": "evaluator",
        "inputs": ["DocumentIR", "DocumentIR", "CandidateContext"],
        "outputs": ["UnifiedSafetyDecision"],
        "description": "Aggregate all safety/quality gates into a unified decision",
        "mode_switches": {"UNIFIED_SAFETY_MODE": ["off", "shadow"]},
    },
    "DocumentValidator": {
        "type": "validator",
        "inputs": ["DocumentIR", "list[NormalizedQuestion]"],
        "outputs": ["DocumentValidationResult"],
        "description": "Cross-question validation — numbering, option keys, dedup, binding integrity",
        "mode_switches": {},
    },
    "ReviewArtifactBuilder": {
        "type": "builder",
        "inputs": ["PipelineExecutionContext", "DocumentIR", "list[NormalizedQuestion]"],
        "outputs": ["ReviewArtifact"],
        "description": "Build comprehensive review artifact with all pipeline metadata",
        "mode_switches": {},
    },
    "TransactionalPersistenceCoordinator": {
        "type": "coordinator",
        "inputs": ["QuestionImport", "ReviewArtifact"],
        "outputs": ["int"],
        "description": "Transactional DB persistence across questions, reviews, artifacts",
        "mode_switches": {"PERSISTENCE_MODE": ["legacy", "transactional_shadow", "transactional"]},
    },
    "AssetOutbox": {
        "type": "outbox",
        "inputs": ["OutboxEvent"],
        "outputs": [],
        "description": "Reliable outbox for asset operations (delete, confirm) with retry",
        "mode_switches": {},
    },
}

# ---------------------------------------------------------------------------
# Current implementation files
# ---------------------------------------------------------------------------

CURRENT_FILES: list[tuple[str, str, int]] = []

for base, label in [(FEATURES, "features"), (CORE, "core"), (SERVICES, "services"),
                     (OCR_WORKER, "ocr_worker")]:
    for f in sorted(base.glob("*.py")):
        if f.name.startswith("_"):
            continue
        lines = len(f.read_text().splitlines())
        CURRENT_FILES.append((str(f.relative_to(REPO)), label, lines))

# ---------------------------------------------------------------------------
# Component mapping rules
# ---------------------------------------------------------------------------

# Each rule: (component_glob, file_pattern, reason)
COMPONENT_MAP: dict[str, list[tuple[str, str]]] = {
    "ControlPlaneFacade": [
        ("**/pipeline_orchestrator.py", "orchestrator contains the current job/task orchestration logic"),
        ("**/pipeline_fingerprint.py", "fingerprint used for run identity"),
        ("**/ocr_canary.py", "canary/rollout configuration"),
    ],
    "PipelineExecutionContext": [
        ("**/pipeline_fingerprint.py", "fingerprint is a core context component"),
        ("**/ocr_runtime_config.py", "runtime config reads env vars that context should carry"),
        ("**/config.py", "global config — context freezes a snapshot"),
    ],
    "InputGateway": [
        ("**/ocr_service.py", "current input entry point"),
        ("**/import_pipeline_service.py", "import pipeline entry point"),
        ("**/ocr_request.py", "OCRRequest defines the input contract"),
    ],
    "InputSafetyValidator": [
        ("**/upload_validator.py", "file upload validation exists"),
        ("**/security.py", "security checks exist"),
        ("**/resource_guard.py", "resource limit guarding exists"),
    ],
    "NativeTextProbe": [
        ("**/pdf_text_normalizer.py", "PDF text layer extraction exists"),
        ("**/page_classifier.py", "page classification exists"),
    ],
    "PageRenderer": [
        ("**/pdf_renderer_service.py", "PDF rendering exists"),
        ("**/visual_region_cropper.py", "region cropping exists"),
    ],
    "PageStream": [
        ("**/pipeline_artifacts.py", "artifact workspace supports staged persistence"),
        ("**/pipeline_checkpoint.py", "checkpoint/resume infrastructure exists"),
        ("**/ocr_worker/workspace.py", "worker workspace manages temp files"),
    ],
    "OCRGateway": [
        ("**/ocr_adapter.py", "OcrAdapter + AdapterRegistry + AdapterSelector are the gateway internals"),
        ("**/ocr_service.py", "OCR service dispatches to backends"),
        ("**/ocr_mode.py", "OCR mode switching exists"),
    ],
    "AdapterRegistry": [
        ("**/ocr_adapter.py", "AdapterRegistry class at line 831"),
    ],
    "AdapterSelector": [
        ("**/ocr_adapter.py", "AdapterSelector class at line 901"),
    ],
    "DocumentIR": [
        ("**/document_ir.py", "DocumentIR with full IR hierarchy, stable IDs, serialization"),
    ],
    "ReadingOrderCoordinator": [
        ("**/reading_order.py", "ReadingOrderResolver exists"),
        ("**/pipeline_stages/reading_order_stage.py", "reading order stage exists"),
    ],
    "DomainParsingCoordinator": [
        ("**/question_splitter.py", "question splitting exists"),
        ("**/question_normalizer.py", "question normalization exists"),
        ("**/question_numbering.py", "numbering parser exists"),
        ("**/cross_page_linking.py", "cross-page linking exists"),
        ("**/answer_matcher.py", "answer matching exists"),
        ("**/structure_analyzer.py", "structure analysis exists"),
        ("**/exercise_region_detector.py", "exercise region detection exists"),
    ],
    "CorrectionCoordinator": [
        ("**/ocr_correction.py", "OCR correction exists"),
        ("**/ai_repair.py", "AI repair exists"),
        ("**/code_detector.py", "code detection exists"),
        ("**/code_integrity.py", "code integrity exists"),
        ("**/code_structure_reconstructor.py", "code structure reconstruction exists"),
        ("**/layout_reconstruction.py", "layout reconstruction exists"),
        ("**/vision_fallback.py", "vision fallback exists"),
        ("**/ocr_fix/", "OCR fix directory exists"),
        ("**/ocr_vl/", "OCR-VL directory exists"),
    ],
    "UnifiedSafetyEvaluator": [
        ("**/candidate_evaluator.py", "candidate evaluation exists"),
        ("**/ai_safety.py", "AI safety evaluation exists"),
        ("**/quality_gate.py", "domain quality gate exists"),
        ("**/ocr_quality_gate.py", "OCR quality gate exists"),
    ],
    "DocumentValidator": [
        ("**/batch_validation.py", "batch validation exists"),
        ("**/ai_validation.py", "AI validation exists"),
    ],
    "ReviewArtifactBuilder": [
        ("**/pipeline_artifacts.py", "pipeline artifact building exists"),
        ("**/review_service.py", "review service builds review data"),
    ],
    "TransactionalPersistenceCoordinator": [
        ("**/question_import_writer.py", "question import DB writing exists"),
        ("**/import_pipeline_service.py", "import pipeline manages DB persistence"),
        ("**/import_service.py", "import service manages writes"),
    ],
    "AssetOutbox": [
        ("**/asset_reference_service.py", "asset reference management exists"),
        ("**/storage_backend.py", "storage backend exists"),
    ],
}


def file_matches_pattern(file_rel: str, pattern: str) -> bool:
    """Check if a file path matches a glob-like pattern."""
    if pattern.endswith("/"):
        return pattern.rstrip("/") in file_rel
    # Convert **/ prefix to wildcard
    pat = pattern.replace("**/", "")
    return pat in file_rel


def build_mapping() -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for component, rules in COMPONENT_MAP.items():
        matched_files: list[dict[str, Any]] = []
        for file_rel, _label, _lines in CURRENT_FILES:
            for pattern, reason in rules:
                if file_matches_pattern(file_rel, pattern):
                    matched_files.append({
                        "file": file_rel,
                        "reason": reason,
                    })
                    break
        target = TARGET_COMPONENTS.get(component, {})
        mapping[component] = {
            "type": target.get("type", "unknown"),
            "status": "exists" if matched_files else "missing",
            "description": target.get("description", ""),
            "current_files": matched_files,
            "mode_switches": target.get("mode_switches", {}),
            "gap": "exists" if matched_files else "MISSING — needs new implementation",
        }
    return mapping


def build_call_graph() -> dict[str, Any]:
    """Extract known import relationships from features/core to services."""
    edges: list[dict[str, str]] = []
    modules: dict[str, str] = {}

    for base_dir, label in [(FEATURES, "features"), (CORE, "core")]:
        for f in sorted(base_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            rel = str(f.relative_to(REPO))
            modules[rel] = label
            content = f.read_text()
            # Find imports from app.features, app.core, app.services
            for m in re.finditer(r"(?:from|import)\s+app\.(\w+)\.(\w+)", content):
                target_pkg = m.group(1)
                target_mod = m.group(2)
                if target_pkg in ("features", "core", "services", "ocr_worker"):
                    edges.append({
                        "source": rel,
                        "target": f"app/{target_pkg}/{target_mod}.py",
                        "type": "import",
                    })

    return {
        "modules": modules,
        "edges": edges,
        "stats": {
            "total_modules": len(modules),
            "total_edges": len(edges),
        },
    }


def find_gaps(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify gaps between current implementation and target architecture."""
    gaps: list[dict[str, Any]] = []

    for component, info in mapping.items():
        if info["status"] == "missing":
            gaps.append({
                "component": component,
                "severity": "HIGH" if info["type"] in ("gateway", "coordinator") else "MEDIUM",
                "type": "missing",
                "detail": f"No dedicated implementation found for {component}",
            })
            continue

        # Check mode switch readiness
        mode_switches = info.get("mode_switches", {})
        if mode_switches:
            for var, modes in mode_switches.items():
                if "shadow" in modes:
                    gaps.append({
                        "component": component,
                        "severity": "LOW",
                        "type": "mode_switch_needed",
                        "detail": f"Needs {var} env var with modes {modes}",
                    })

        # Check if orchestration is scattered
        if component in ("DomainParsingCoordinator", "CorrectionCoordinator"):
            files = info.get("current_files", [])
            if len(files) > 5:
                gaps.append({
                    "component": component,
                    "severity": "MEDIUM",
                    "type": "scattered_implementation",
                    "detail": f"Capability spread across {len(files)} files, needs Coordinator facade",
                })

    return gaps


def main() -> None:
    mapping = build_mapping()
    call_graph = build_call_graph()
    gaps = find_gaps(mapping)

    # Write JSON outputs
    for name, data in [
        ("current_to_target_map.json", mapping),
        ("call_graph.json", call_graph),
        ("architecture_gaps.json", gaps),
    ]:
        path = OUT / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"  Wrote {path.relative_to(REPO)}  ({len(json.dumps(data))} bytes)")

    # Write human-readable markdown
    md_lines = [
        "# 当前架构到目标架构映射\n",
        f"生成时间: 2026-07-18\n",
        f"分析覆盖: {len(CURRENT_FILES)} 个源文件\n",
        "## 映射概要\n",
        "| 目标组件 | 状态 | 当前实现文件 | 改造风险 |",
        "|---------|------|------------|---------|",
    ]
    for comp, info in sorted(mapping.items()):
        files = info.get("current_files", [])
        status = "✅ 已存在" if info["status"] == "exists" else "❌ 缺失"
        file_list = ", ".join(f"`{f['file']}`" for f in files[:5])
        if len(files) > 5:
            file_list += f" 等 {len(files)} 个文件"
        risk = "低" if info["status"] == "exists" else "高"
        md_lines.append(f"| {comp} | {status} | {file_list} | {risk} |")

    md_lines.extend([
        "",
        "## 架构差距分析\n",
        "| 组件 | 严重程度 | 类型 | 详情 |",
        "|------|---------|------|------|",
    ])
    for g in gaps:
        md_lines.append(f"| {g['component']} | {g['severity']} | {g['type']} | {g['detail']} |")

    md_path = OUT / "current_to_target_map.md"
    md_path.write_text("\n".join(md_lines))
    print(f"  Wrote {md_path.relative_to(REPO)}  ({len(md_lines)} lines)")


if __name__ == "__main__":
    main()

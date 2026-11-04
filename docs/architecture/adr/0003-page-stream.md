# ADR-0003: Page Stream — Windowed Page Iteration

**Status:** Accepted (2026-07-18)

## Context

Full-document PDF rendering loads all pages into memory simultaneously. For 1000-page textbooks, this causes OOM. Resume after crash requires re-rendering all pages.

## Decision

Introduce `PageStream` with windowed page iteration:

- `window_size=3`, `overlap=1` (configurable)
- Rendered pages are atomically persisted to disk before yielding
- Resume reuses artifacts with matching checksums
- Memory is O(window_size), not O(total_pages)
- Temporary and final artifacts are separated
- `PAGE_STREAM_MODE=legacy|stream` (default: stream)

## Alternatives

- **Render all pages upfront**: Rejected — OOM on large documents
- **Single-page-at-a-time**: Rejected — no overlap context for cross-page detection
- **Database-backed**: Rejected — too heavy for page images

## Consequences

- 100, 500, 1000 page tests show memory proportional to window_size only
- Resume does not re-render pages with valid checksums
- Overlap enables cross-page context during windowed processing

## Rollout

`PAGE_STREAM_MODE=stream` by default. Legacy mode keeps old behavior.

## Rollback

Set `PAGE_STREAM_MODE=legacy`.

## Metrics

- `test_page_stream_memory.py` verifies bounded memory
- `test_page_stream_resume.py` verifies artifact reuse

## Legacy Removal Criteria

When no pipeline uses legacy full-document rendering.

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录

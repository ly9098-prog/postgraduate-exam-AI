# Refactor continuation — new chat entrypoint

## Goal and boundaries (re-read before any work)
- ACTIVE: compatibility-preserving full-stack refactor for MemoGrad/postgraduate-ai. Keep UI/API/DB/storage/queue/auth/transactions/errors/cancellation/live dynamic ports.
- Workflow: characterize first; equivalent extractions only; new modules <=300 lines / functions <=50; independent read-only review closes ALL findings incl. P3 before explicit-path local commit. `git add` only named paths, never `-A`/`-am`; no push/deploy/production/data mutation/amend/reset/checkout; never touch protected evidence or data. Commit: Conventional Commits, Chinese scope ok, author lmh, no AI attribution.
- User authorized the established per-batch local commit loop; production or anything destructive still needs explicit new approval.

## State (verified 2026-10-29)
- HEAD `7c3952d2` refactor(miniprogram): 收敛刷题结果页 controller 装配; `main` ahead 38 vs local origin/main ref (not fetched). No push/deploy.
- Committed adapter chain: `ed6a299f` practice scoring → `1901303e` mastery → `83e1fbaf` knowledge points → `efb4fbce` knowledge path → `3a652cf7` stats → `623d2444` Pomodoro service → `871d8705` OCR chunk/router → `3bca9350` practice/stats controllers → `81864c03` study plan → `02f4d5f3` exam adapters → `e70a1bb5` review adapters → `86e759eb` Pomodoro adapters (52 ports, page 2184→1596) → `7c3952d2` practice-result adapters.
- Last batch evidence: practice-result/index.js 896→823, 5 adapters (161 lines), gate `miniprogram/scripts/architecture/practice-result-boundaries.js` (286 lines, 22 modules), tests module-boundaries 9 + page-adapter-contracts 6, full `node --test tests/*.js` 2128 passed, render regression 31/31, independent review no findings (27 HEAD-diff assertions). Logs `/tmp/pr-adapter/*.log` (may vanish on reboot).
- Tasklog execution records live in `prompts/tasks/current_task.md` §276 and historical sections; `docs/architecture/REFACTOR_INVENTORY.md` and `docs/architecture/MEMORY_SYSTEM.md` already synced to current facts.

## Uncommitted protected user paths (NEVER stage/revert/delete)
- AGENTS.md; CLAUDE.md; docs/INDEX.md; docs/MEMORY_SYSTEM.md; docs/architecture/MEMORY_SYSTEM.md; docs/admin/PHASE_PLAN.md, README.md, REVIEW_FLOW.md; docs/backend/API_SPEC.md; docs/development/ (4 external reference docs); deleted prompts/tasks/current-task.md and prompts/tasks/ocr_book_pdf_non_question_filter_plan.md; prompts/tasks/current_task.md log additions (§276 + P3 header fix already applied); prompts/tasks/current2.md; backend/service_compatibility.py (Ruff diagnostic text, not source).
- Baseline is user-intended edits; only implementation/test/CI docs for a batch get staged.

## Known issues / not defects to "fix"
- re_pending re-review/rollback and issuance Leitner filtering are ALREADY implemented (`8829a49f`, `7ea3dc2a`; `practice/candidate_schedule.py`). Do not reimplement.
- HEAD-baseline CI failures unchanged: `test-v5-ui-fixes.js`, `test-v8-fixes.js`, `test-408-feature-integration.js`; pomodoro resilience has 1 pre-existing `client_start_id` failure.
- `/tmp/pa-head` worktree (detached e70a1bb5) still registered; can be removed when no longer needed. Do not rerun one-shot `/tmp` extractors.
- Unverified everywhere: real WeChat tool/device, external OCR/AI, production Admin browser, full worker/multi-dispatcher, Redis full-failure recovery in production, backup-restore drill, PG/Redis production concurrency. Do not claim these.

## Next work (priority order)
1. Backend learning domain: `backend/app/services/knowledge_map_service.py` 942 lines; 7 functions >50 (`get_point_detail` 172, `_build_hierarchy_metadata` 119, `_node_payload` 95, `_build_subject_summary` 76, `get_subject_map` 76, `_relation_payloads` 74, `get_overview` 62). Characterize with `backend/tests/test_services/test_knowledge_map_compatibility.py` (5 async tests, real SQLite) before splitting hierarchy metadata / node payload / subject summary responsibilities. Baseline doc: `docs/architecture/KNOWLEDGE_GRAPH_COMPATIBILITY.md` (2026-10-24).
2. Then wrong-book(1547)/wrong-detail(1653) size debt; practice.js remaining page responsibilities; pomodoro-stats view write-backs (worst fn 35).
3. Backend queue `task_queue_service.py` 2345, OCR `pipeline_orchestrator.py` 4441, `ai_service.py` 702 remaining >50 functions. Phase0 semantic baseline, Admin questions/review remaining orchestration, full-stack budget gates and compat cleanup remain open.
4. Mini gates after each mini batch (from miniprogram/): page-budgets, learning-controller-budgets, pomodoro-boundaries, exam-runner-boundaries, review-today-boundaries, practice-result-boundaries; plus full `node --test tests/*.js` and render regression. Backend: strict Ruff + compileall + affected pytest.

## Tools
- Backend venv `backend/.venv/bin/python` (actual 3.12); test env: APP_ENV=test DEPLOYMENT_PROFILE=local_import APP_SECRET=test-secret DATABASE_URL=sqlite+aiosqlite:///:memory: REDIS_URL='' SENTRY_DSN='' STAGING_STORAGE_DIR=/tmp/<batch>.
- Exact-CI replay `/tmp/replay_ai_failure_final_ci.py` if needed. Review agents available read-only: Descartes 01a1790b-4c57-7033-a38e-7080e078771e, Cicero 01a1792e-10a9-76e0-836e-7bf320ab25eb.

## Continuation update — 2026-10-29 (supersedes State/Next work above)
- HEAD `65642c81`, main ahead 41 vs unchanged local origin/main ref; no fetch/push/deploy. Index empty.
- Completed in order: `8a57a68d` knowledge-map projections; `f0103ae7` knowledge-map queries/topology/relations/detail orchestration; `65642c81` wrong-book list/statistics projections. Logs appended as current_task.md §§277–279; existing task-log text preserved byte-for-byte.
- Knowledge-map service 942→195 lines; 8 `knowledge_map*.py` modules all <=300 lines/functions <=50. Canonical scope, query order/SQL/parameters, subject-vs-subtree aggregation differences, relation sorting/truncation, detail field order and practice params preserved. Affected pytest 159 passed; global architecture/dependency 53 passed; strict Ruff/compileall/YAML/diff passed. Independent review no remaining findings; independent 600 three-entry comparisons plus 11,250 projection and 5 real SQLite comparisons passed. Docs `KNOWLEDGE_GRAPH_COMPATIBILITY.md` §§5–6; gate `tests/architecture/test_knowledge_map_boundaries.py` (14 tests).
- Wrong-book page 1547→1306; 27 methods moved to value/item/analysis views and live getter adapter in `wrong-book/utils/` (82/130/143/37 lines). Static helpers still injected from original page imports; dynamic helper replacement/binding preserved. Full node tests 2141 passed; render 31/31; final targeted 14 passed; 7 gates passed. Independent review P3 new-Function bypass repaired with negative cases; no remaining findings. Differential: 27 bodies/107 remaining properties unchanged, 9,944 + independent 3,007 comparisons passed. Docs `WRONG_BOOK_COMPATIBILITY.md`; gate `scripts/architecture/wrong-book-boundaries.js`.
- Preserved original dirty paths: verified 11 tracked diffs exactly equal initial snapshot; original current_task.md is an exact prefix. All original untracked paths retained. Rules/hand-off/log files remain unstaged; no user data/diagnostic cleanup.
- NEXT: wrong-detail (1653) size debt and wrong-book remaining request/batch/AI orchestration. Wrong-detail only read this run, no edits: it already has `utils/teacher-action-controller.js` and one inline capabilities object; static render/AI helpers at page top and navigation/AI/recovery/diagnosis responsibilities remain. Source-inspection scripts `test-wrong-detail-ai-math.js`, `test-wrong-detail-ai-visual.js`, `test-error-diagnosis.js`, `test-408-ai-teacher.js` must follow ownership if later moved. Keep known pre-existing failures unchanged.
- THEN: practice.js remaining responsibilities, pomodoro-stats view write-backs; queue/OCR/AI remaining >50 functions, phase0 semantic inventory/Admin remaining orchestration/full-stack gates/compat cleanup. Overall refactor active; all prior real-environment acceptance limits remain.
- Evidence `/tmp/knowledge-map-batch/` and `/tmp/wrong-book-view-batch/`; do not rerun their one-shot extraction scripts. No new production authorization.


## Continuation update — wrong-detail state (2026-10-29)
- HEAD `2f3c870b`, main ahead1 vs origin/main `65642c81` (external push updated this ref on 2026-10-29 15:33:36 +0800; user confirmed continuation); index empty. Local-only explicit13-path commit; protected original11 tracked patches verified unchanged.
- Wrong-detail1653→1533; three modules ai-state88/question-view28/teacher-page-adapter37. Original controller unchanged; 8 helper bodies/118 other properties/22 ports verified; 9000 comparisons, original8 contracts, current15 targeted, fullNode2156/render31/eight gates passed. Independent review incl final CI/docs no P0–P3. Evidence `/tmp/wrong-detail-state-batch/`; do not rerun one-shot extract.js/make-gate.js.
- CI source checks: visual/math pass; 408 teacher ownership updated only for wrong-detail, still pre-existing practice-result API literal failure; error-diagnosis unchanged pre-existing practice-result occurrence diagnosis_id failure. Both reproduced with original page.
- NEXT wrong-detail navigation/AI recovery/regeneration/diagnosis, wrong-book request/batch/AI; all broader outstanding scope and real-environment restrictions above continue. Overall goal active. Tasklog §280; logs/rules/handoff stay unstaged.


## Continuation update — wrong-detail transitions (2026-10-29)
- HEAD `88830317`, main ahead2 vs origin/main `65642c81` (corrected against the external ref update, user confirmed continuation); index empty. Explicit9-path local commit. Wrong-detail1533→1454;10 methods→content-transition132 lines, explicitpage/original constants+_sleep, no shared state/new controller.
- Original11 contracts passed; current26; fullNode2167/render31/eight gates passed. 10 bodies receiver-only replacement,109 remainingPage properties unchanged;6000 deterministic timer/state/patch comparisons identical; independent code/docs reviews no P0–P3, frozen9 paths unchanged postcommit. Tasklog§281, compatibility§4.
- Evidence `/tmp/wrong-detail-transition-batch/` includes before.js, original-preload.js, audit.js and logs; never rerun extract.js. Original11 dirty tracked patches preserved. Protected rules/tasklog/context remain unstaged.
- NEXT wrong-detail navigation data/AI recovery/regeneration/diagnosis,wrong-book request/batch/AI; then broader outstanding work above. Existing two legacy practice-result source-check failures and real-device/network/AI acceptance gaps remain. Overall goal active.


## Continuation update — wrong-detail navigation (2026-10-29)
- User confirmed continue after origin/main ref moved to `65642c81`; no push this turn. HEAD `d84d514c`, ahead3 vs origin/main; index empty. Corrected previous records: 2f3c870b was ahead1; 88830317 ahead2 at those points.
- Wrong-detail1454→1355; navigation-data51/navigation-flow76, six original page methods exact delegates. API/storage/toast invocation-time injection and await-late renderer/helper calls preserve live resolution; sequencing/cache/animation/error/storage semantics unchanged.
- Pre-extraction11 and final original replay13 passed; current four focused suites39; full Node2180; render31; eight gates, syntax, visual/math and YAML passed; independent 800-case compare and P0-P3 review clean. 11 frozen paths hashes. Tasklog§282, compatibility doc§5.
- Commit `d84d514c3f3cc5b7ffd64194407d13f31b4a6345`, explicit11 paths, local only. Protected dirty files and task logs remain unstaged. Evidence `/tmp/wrong-detail-navigation-batch/`; do not rerun one-shot extract.js.
- NEXT wrong-detail AI generation/recovery/regeneration/diagnosis, then wrong-book orchestration. Existing legacy practice-result source assertion failures and true WeChat/external AI/e2e limits stand. Overall goal remains active.


## Continuation update — wrong-detail AI recovery (2026-10-29)
- HEAD `74a35fa8`, main ahead4 vs origin/main `65642c81`; index empty, explicit10-path local commit, no push/deploy/data operations. Original protected files verified unchanged before/after commit; tasklog/context appended only and remain unstaged.
- Wrong-detail1355→1302; three request identity/persisted polling/recovered application methods→ai-recovery64 lines. 44 attempts/43 delays, guards/catch/sleep/live API receiver/await-late normalizers/cache/writeback order preserved; 116 other Page properties unchanged.
- Original replay12 contracts/current51 targeted/fullNode2192/render31/eight gates/syntax/visual/math/YAML/diff pass; 800 deterministic comparisons identical; independent code+docs reviews clean P0–P3. Legacy practice-result source-check failures reproduced before/current. Compatibility§6, inventory, CI/gates synced; tasklog§283.
- Evidence `/tmp/wrong-detail-ai-recovery-batch/`; do not rerun `extract-recovery.js`. NEXT wrong-detail generation/regeneration/background recovery/diagnosis orchestration, then wrong-book requests/batch/AI and broader list above. Real WeChat/external AI/production/full-flow acceptance gaps remain; overall ACTIVE.


## Continuation update — wrong-detail ordinary AI generation (2026-10-29)
- HEAD `b004ea82`, main ahead5 vs origin/main `65642c81`; index empty, explicit9-path local commit, author lmh/no AI trailer. No push/deploy/production/data operations; protected files verified unchanged before/after commit, then tasklog/context append-only and unstaged.
- Page1302→1245; ordinary generation entry/result/success/error four methods→ai-generation75 lines. Receiver-only body change;115 other Page properties identical. Guard/baseline/sequence/loading/cancel reset, generating/fallback/empty/success priority, live methods/helpers/console, nonawaited enqueue and recovery/writeback/error propagation preserved.
- Original12/current63/fullNode2204/render31/eight gates/syntax/visual/math/YAML/diff pass;800 four-entry state/trace/field-order comparisons identical; code+docs independent reviews clean P0–P3;9 frozen paths match. Compatibility§7/inventory/CI synced; tasklog§284. Evidence `/tmp/wrong-detail-ai-generation-batch/`; do not rerun `extract-generation.js`.
- NEXT regeneration/background recovery/request protocol/diagnosis, then wrong-book requests/batch/AI and full remaining plan. Existing legacy practice-result assertions and real-environment gaps remain; overall ACTIVE.


## Continuation update — wrong-detail AI regeneration (2026-10-29)
- HEAD `33ee6b53`, main ahead6 vs origin/main `65642c81`; explicit9-path local commit/empty index/no AI trailer/no push/deploy/data. Protected hashes verified before/after commit, tasklog/context append-only and unstaged.
- Page1245→1143; ten regeneration methods→ai-regeneration144 lines,109 other Page properties unchanged. Preserve snapshot/live helper/branch/cache-preserved/history/marker/writeback/toast semantics, catch/dispatcher nonawaited recovery and live wx receiver.
- Original15/current78/fullNode2219/render31/eight gates/syntax/visual/math/YAML/diff pass;1200 ten-entry comparisons identical; independent code+docs reviews clean P0–P3,9 frozen hashes match. Compatibility§8/inventory/CI synced;tasklog§285. Evidence `/tmp/wrong-detail-ai-regeneration-batch/`; do not rerun `extract-regeneration.js`.
- NEXT AI request/background recovery enqueue/cache and diagnosis orchestration;then wrong-book and remaining full-stack plan. Legacy source-check failures and real-environment gaps remain;overall ACTIVE.


## Continuation update — wrong-detail AI request support (2026-10-29)
- HEAD `966e9697`, main ahead7 vs origin/main `65642c81`; explicit10-path local commit/empty index/author lmh/no AI trailer/no push/deploy/production/data. Protected hashes verified before/after commit; tasklog/context append-only and unstaged.
- Page1143→1101; six reset/cache/request/enqueue/failure/tap methods→ai-request68 lines;113 other Page properties unchanged. Live API/wx receiver,55000/10000ms,payload force/baseline/field order,error propagation vs enqueue catch/warn/false,cache identity/data/marker/status,tap no Promise return preserved.
- Original13/current91/fullNode2232/render31/eight gates/syntax/visual/math/YAML/diff pass;900 six-entry comparisons identical; independent code+docs reviews clean P0–P3;10 frozen hashes match. Compatibility§9/inventory/CI synced;tasklog§286. Evidence `/tmp/wrong-detail-ai-request-batch/`; do not rerun `extract-request.js`.
- NEXT diagnosis (open/close/select/toggle/save/next action/refresh), detail load/lifecycle/master/undo remaining responsibilities, then wrong-book requests/batch/AI and broader full-stack list. Diagnosis source-check currently fails earlier at known practice-result assertion; preserve that failure while updating ownership if extracting wrong-detail. Real-environment/full-flow gaps remain;overall ACTIVE.


## Continuation update — wrong-detail diagnosis (2026-10-29)
- HEAD `92c619f6`,main ahead8 vs origin/main `65642c81`;explicit11-path local commit/empty index/author lmh/no AI trailer/no push/deploy/data. Protected hashes verified before/after commit;tasklog/context append-only and unstaged.
- Page1101→963;7 diagnosis sheet/select/save/next action/refresh methods→diagnosis-flow168;112 other Page properties unchanged. Injected API/diagnosis object+live platform getter preserve evaluation order/receiver/late helpers/cache/confirmed fallback/finally semantics.
- Original15/current106/fullNode2247/render31/eight gates/syntax/visual/math/YAML/diff pass;1120 seven-entry comparisons identical;code+docs independent review clean P0–P3;11 hashes match. Compatibility§10/inventory/CI synced;tasklog§287. Evidence `/tmp/wrong-detail-diagnosis-batch/`;never rerun `extract-diagnosis.js`.
- Existing baseline limitation newly characterized: data-wrapped save response retains nested data;normalizer can still use old inner primary/confirmed despite outer local override. Preserved;do not silently fix in equivalent refactor. Legacy diagnosis wrongdetail assertions moved+isolated pass;full original/current still practice-result diagnosis_id failure.
- NEXT detail load/lifecycle/master/undo remaining,then wrong-book and full-stack list. Real-environment/full-flow gaps remain;overall ACTIVE.


## Continuation update — wrong-detail load/prefetch (2026-10-29)
- HEAD `f3c690c8`,main ahead9 vs origin/main `65642c81`;explicit10-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Protected hashes checked before/after commit;tasklog/context append-only and unstaged.
- Page963→867;eight load/initial patch/projection/preferred analysis/render/error/prefetch methods→load-flow130;111 other Page properties unchanged. Preserve cache-before-projection/sequence+guards/private writes/two normalizations/live helpers/nonawait diagnosis/invariant-before-trace;prefetch300000ms/newer-cache protection/undefined return/sync-vs-async errors.
- Original15/current121/fullNode2262/render31/eight gates/syntax/visual/math/YAML/diff pass;1000 eight-entry comparisons identical;code+docs independent reviews clean P0–P3;10 frozen hashes match. Compatibility§11/inventory/CI synced;tasklog§288. Evidence `/tmp/wrong-detail-load-batch/`;never rerun `extract-load.js`.
- NEXT lifecycle/master/undo/remove remaining,then wrong-book and full-stack list. Existing data-envelope/legacy/full-flow and real-environment limitations remain;overall ACTIVE.


## Continuation update — wrong-detail lifecycle (2026-10-29)
- HEAD `23b98e33`,main ahead10 vs origin/main `65642c81`;explicit10-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Protected hashes before/after commit match;tasklog/context append-only and unstaged.
- Page867→771;twelve lifecycle/init/navigation-source/bottom-action/timer/unload methods→lifecycle146;107 other Page properties unchanged. Preserve null-prototype/new caches/data+controller identity/live wx and hooks/30min TTL/ID normalization/load-no-await/3000ms idle recalculation/ordered unload and partial-error cleanup.
- Original14/current135/fullNode2276/render31/eight gates/syntax/visual/math/YAML/diff pass;1000 comparisons identical;code+docs independent reviews clean P0–P3;10 frozen hashes match. Compatibility§12/inventory/CI synced;tasklog§289. Evidence `/tmp/wrong-detail-lifecycle-batch/`;never rerun `extract-lifecycle.js`.
- NEXT master/undo/remove/render-safety remaining,then wrong-book and broader full-stack list. Existing baseline and real-environment limits remain;overall ACTIVE.


## Continuation update — wrong-detail master/undo (2026-10-29)
- HEAD `86f09f01`,main ahead11 vs origin/main `65642c81`;explicit10-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Protected hashes before/after commit match;tasklog/context append-only and unstaged.
- Page771→620;nine master/unmaster methods→master-flow130,eight undo/timer/error/commit methods→master-undo93;102 other Page properties unchanged. Preserve ID/busy/skip/count/cache-view identity/live API+wx/hooks/5000ms+120ms/current-index callback/finally semantics.
- Original15/current150/fullNode2291/render31/eight gates/syntax/visual/math/YAML/diff pass;1360 comparisons identical;code+docs independent reviews clean P0–P3;10 frozen hashes match. Compatibility§13/inventory/CI synced;tasklog§290. Evidence `/tmp/wrong-detail-master-batch/`;never rerun `extract-master.js`.
- Baseline limitations characterized+preserved: undo404/410 still commits and emits success after missing toast;timer-clear before try can leave inflight=true if it throws. Do not silently fix during equivalent refactor.
- NEXT remove/render-safety/teacher remaining,then wrong-book and full-stack list;all prior baseline/real-environment limits remain;overall ACTIVE.


## Continuation update — remove batch and confirmed rules (2026-10-29)
- HEAD `7d5fc800`, explicit9-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Page620→579;five remove/menu/confirm methods→remove-flow63;114 other Page properties unchanged.
- Original9/current159/fullNode2300/render31/eight gates/syntax/visual/math/YAML/diff pass;1000 comparisons identical;code+docs independent reviews clean P0–P3;9 committed hashes verified. Compatibility§14/inventory/CI synced;tasklog§291 now appended unstaged. Evidence `/tmp/wrong-detail-remove-batch/`;never rerun `extract-remove.js`.
- AGENTS changed externally during precommit; shell did not stop after hash failure, but commit contains only9 reviewed task paths. User explicitly confirmed new rules/resupplied AGENTS. On resumption CLAUDE already references AGENTS; both preserved as current user edits. All other old protected paths matched. Future validation+commit run in one fail-closed Python process.
- Code search: installed `codebase-memory-mcp cli` exposes MCP tools; index_status ready (2026-10-29T10:46:30Z). Docs search: graphify skill present, repo graph absent; do not claim graph coverage.
- NEXT render-safety/teacher interactions,then wrong-book and full-stack remaining list. All baseline/real-environment limits remain;overall ACTIVE.


## Continuation update — wrong-detail remaining boundaries (2026-10-29)
- HEAD `a66f1b55`,explicit11-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Page579→502;3render methods→render-safety63;4teacher interaction methods→teacher-interaction46;112 other Page properties unchanged. Eight original thin handlers retained;all104Page methods+4free helper wrappers freeze108 templates;19 modules300/50;unregistered callable/spread rejected.
- Original11/current171/fullNode2312/render31/eight gates/syntax/visual/math/both CI YAML/diff pass;1400 comparisons identical;code+docs independent reviews clean P0–P3;11 source/19 protected hashes match before+after commit. Compatibility§15/inventory/reliability synced;ci.yml has no mini job. Tasklog§292 appended unstaged. Evidence `/tmp/wrong-detail-remaining-batch/`;never rerun `extract-remaining.js`.
- New AGENTS/CLAUDE current user edits protected;validated+committed in same fail-closed Python process. Installed codebase-memory-mcp CLI tools work;index_status ready and 5 paths metadata_match(best effort). graphify query via PYTHONPATH skill package returned missing graph;no graph coverage claim.
- NEXT wrong-book1306 request/batch/AI orchestration,then practice/pomodoro-stats and backend queue/OCR/AI,Phase0/Admin/full-stack gates+real acceptance. All baseline/legacy/real-environment limits remain;overall ACTIVE.


## Continuation update — wrong-book loading requests (2026-10-29)
- HEAD `76e42e53`,main ahead14 vs local origin/main `65642c81`;explicit10-path local commit/empty index/author lmh/noAI trailer/no push/deploy/production/data. Same-process fail-fast validation+commit;10 frozen and19 protected hashes match before/after. Tasklog§293/context appended only and unstaged.
- Wrong-book1306→1141;six filter reload/page/stats/list/task/subjects methods→request-flow191 lines/functions≤50;128 other Page properties unchanged. Date/params try boundaries,request-specific guards,two list guards,await-late helper/state,Promise.all order,high-frequency global precedence and nonawait reset task flow preserved.
- Original14/current28 focused/fullNode2326/render31/eight gates/syntax/visual/math/YAML/diff pass;1200 six-entry return/state/trace/field-order comparisons identical;independent implementation+final docs/CI reviews no P0–P3.5modules/33delegates/1141 budget;compatibility§4/inventory/reliability synced.
- Evidence `/tmp/wrong-book-request-batch/`;do not rerun `extract-request.js`. NEXT wrong-book lifecycle/selection/batch/undo/AI,then remaining full-stack list above. Real WeChat/external AI/production/full-flow and existing baseline limits remain;overall ACTIVE.


## Continuation update — wrong-book selection/capsule (2026-10-29)
- HEAD `dc432aca`,main ahead15 vs local origin/main `65642c81`;explicit10-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Same-process fail-fast validation+commit;staged blobs match10 frozen hashes;19 protected paths unchanged before/after. Tasklog§294/context append-only and unstaged.
- Wrong-book1141→1028;sixteen view/selection/capsule/tap methods→selection-flow179 lines/functions≤50;118 other Page properties unchanged. Preserve map truthiness/copy/key order/valid-key cleanup/offscreen selections,list duplicates vs task dedup,5000ms capsule,untracked16ms+260ms pulse,700ms tap suppression,dynamic hooks/platform and try/partial-write boundaries.
- Original15/current15/five focused43/fullNode2341/render31/eight gates/syntax/visual/math/YAML/diff pass;1600 entry/state/timer/trace/field-order comparisons identical;independent implementation+final docs/CI reviews no P0–P3.6modules/49delegates/1028 budget;compatibility§5/inventory/reliability synced.
- Evidence `/tmp/wrong-book-selection-batch/`;do not rerun `extract-selection.js`.NEXT wrong-book lifecycle/batch requests+undo/AI,then full-stack list above. Existing baseline/real WeChat/external AI/production/full-flow limits remain;overall ACTIVE.


## Continuation update — wrong-book batch requests/undo (2026-10-29)
- HEAD `d614adf0`,main ahead16 vs local origin/main `65642c81`;explicit11-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Same-process fail-fast validation+commit;staged blobs match11 frozen hashes;19 protected paths unchanged before/after. Tasklog§295/context append-only and unstaged.
- Wrong-book1028→894;twelve menu/confirm/action/rule/result/error/reload methods→batch-flow131 lines;three mastered/undo/clear methods→batch-undo67;functions≤50;119 other Page properties unchanged. Preserve confirmation snapshots/try boundaries/hide-before-destroyed/live handler/skipped-count/5000ms/undefined undo return/then.catch/nonawait reload/live API+platform and partialinFlight.
- New baseline limitation characterized: ordinary batch success without updated_count reads undefined free ids and throws ReferenceError;action catches it. Preserved,do not silently fix. Timer/loading pre-request errors still may retaininFlight;application errors enter original undo retrycatch.
- Original18/current18/six focused61/fullNode2359/render31/eight gates/syntax/visual/math/YAML/diff pass;1500 entry/return/state/timer/trace/field-order comparisons identical;independent implementation+final docs/CI reviews no P0–P3.8modules/64delegates/894 budget;compatibility§6/inventory/reliability synced.
- Evidence `/tmp/wrong-book-batch-actions/`;do not rerun `extract-batch.js`.NEXT wrong-book lifecycle/navigation/export/AI,then remaining full-stack list above. All existing baseline/real-environment/full-flow limits remain;overall ACTIVE.


## Continuation update — wrong-book lifecycle/navigation/export (2026-10-29)
- HEAD `5748c0b9`, main ahead17 vs local origin/main `65642c81`; explicit11-path local commit, empty index, author lmh, no AI trailer/push/deploy/data operations. Same-process fail-fast validation+commit; staged blobs match11 frozen hashes;19 protected paths unchanged before/after. Tasklog§296/context appended and unstaged.
- Wrong-book894→783; five lifecycle methods→lifecycle67 lines; six capability/back/detail/export methods→navigation-flow92; functions≤50;123 other Page properties unchanged. Preserve partial load resets/query/hook order, nonawait ready/show and late diagnosis without added destroyed guard, unload sequence/partial cleanup, strict capability flags/requestId/try/live formatter, raw nav IDs+ts/storage fallback, finite nonzero export IDs/global-write/navigation order and live platform/app receiver.
- Original17/current17/seven focused78/fullNode2376/render31/eight gates/syntax/visual/math/YAML/diff pass;11 AST token-equivalent bodies and1100 entry/return/state/navigation/trace/field-order comparisons identical. Independent implementation+final docs/CI reviews no P0–P3.10modules/75delegates/783budget;compatibility§7/inventory/reliability synced.
- Evidence `/tmp/wrong-book-lifecycle-batch/`; do not rerun `extract-lifecycle.js` (initial regex changed export-config string; contract caught it and route was restored; final AST token checks confirm strings). NEXT wrong-book filter/AI remaining, then full-stack list above. Existing baseline/real-environment/full-flow limits remain; overall ACTIVE.


## Continuation update — wrong-book AI state/persistence (2026-10-29)
- HEAD `108f83c7`, main ahead18 vs local origin/main `65642c81`; explicit11-path local commit, empty index, author lmh, no AI trailer/push/deploy/data operations. Same-process fail-fast validation+commit; staged blobs match11 frozen hashes;19 protected paths unchanged before/after. Tasklog§297/context appended and unstaged.
- Wrong-book783→652; five idle/normalize/content/pending/detail methods→ai-state80 lines; eight user/settings/toggle/cache/signature/commit methods→ai-persistence107; functions≤50;121 other Page properties unchanged. Preserve JSON clone/accuracy/content/details/firstItem reads/user truthy/storage keys/strict true/cache identity/time-before-save/live details/field order;420ms toggle and existing finally/current alive+setting+helper/nonawait semantics.
- Original15/current15/eight focused93/fullNode2391/render31/eight gates/syntax/visual/math/YAML/diff pass;13 AST token-equivalent bodies and1300 entry/return/state/cache/timer/trace/field-order comparisons identical. Independent implementation+final docs/CI reviews no P0–P3.12modules/88delegates/652budget;compatibility§8/inventory/reliability synced.
- Evidence `/tmp/wrong-book-ai-state-batch/`; do not rerun `extract-ai-state.js`. NEXT wrong-book filter/AI request-polling/result-interaction remaining, then full-stack list above. Existing baseline/real-environment/full-flow limits remain; overall ACTIVE.


## Continuation update — wrong-book AI requests/interactions (2026-10-29)
- HEAD `00d2bb18`, main ahead19 vs local origin/main `65642c81`; explicit11-path local commit, empty index, author lmh, no AI trailer/push/deploy/data operations. Same-process fail-fast validation+commit; staged blobs match11 frozen hashes;19 protected paths unchanged before/after. Tasklog§298/context appended and unstaged.
- Wrong-book652→504; nine check/delay/poll/ensure/request/execute/fetch/apply/error methods→ai-request-flow147 lines; three toggle/refresh/feedback methods→ai-interaction53; functions≤50;122 other Page properties unchanged. Preserve strict-zero/dedup/force/cache priority,55000ms/four delay guards/live helper+API,return-vs-await/catch/finally and UI/feedback boundaries.
- New baseline concurrency limitation characterized: executor finally unconditionally clears current promise and can clear a newer stored promise; poll fourth response has no added final guard. Preserved, do not silently fix.
- Original20/current20/nine focused113/fullNode2411/render31/eight gates/syntax/visual/math/YAML/diff pass;12 AST token-equivalent bodies and1200 entry/return/state/request/poll/trace/field-order comparisons identical. Independent implementation+final docs/CI reviews no P0–P3.14modules/100delegates/504budget;compatibility§9/inventory/reliability synced.
- Evidence `/tmp/wrong-book-ai-request-batch/`; do not rerun `extract-ai-request.js`. NEXT wrong-book remaining filter orchestration and complete entry gate, then full-stack list above. Existing baseline/real-environment/full-flow limits remain; overall ACTIVE.


## Continuation update — wrong-book filters and full page gate (2026-10-29)
- HEAD4593692e, ahead20 vs local origin/main65642c81; explicit9-path local commit/empty index/author lmh/noAI trailer/no push/deploy/data. Protected19 and frozen9 hashes plus staged blobs checked in same fail-fast Python process before/after commit; tasklog§299/context append-only and unstaged.
- Page504→478;12 filter/date/params/retry/more methods→filter-flow76 lines/functions≤50. Original10/current/replay pass;targeted126/fullNode2424/render31/eight gates/syntax/visual/math/YAML/diff pass;1200 comparisons identical;122 other unique properties/123 declarations and order unchanged.
- Gate15modules112delegates114unique/115declared methods (originalnoop twice),19private defaults;data object literal only. P3 firstnoop override gap repaired by occurrence checking/negative test;independent implementation+docs reviews clean P0–P3. Compatibility§10/inventory/CI synced; evidence/tmp/wrong-book-filter-batch/,never rerun extract-filter.js.
- Wrong-book current responsibility extraction/entry registration complete, NOT real-client/full-flow acceptance. NEXT practice remaining page responsibilities,pomodoro-stats view writebacks,then backend queue/OCR/AI long functions,Phase0/Admin/full-stack gates and acceptance. All known defects/legacy failures/real-environment limitations above remain;overall ACTIVE.

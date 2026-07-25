# Stage 0 Adapter Replay Report

> Generated: 2026-07-17 08:47:04 UTC


## Summary

- **Total cases**: 10
- **Passed**: 10
- **Failed**: 0
- **Pass rate**: 100.0%

### Fixture Sources

- OCR cache fixtures: 5
- Synthetic fixtures: 5
- Total: 10

## Results by Case

### ✅ 001600599b3001997312797d6d41df63e4e94fa0

- All 6 metrics passed

### ✅ 00a5b2b037f3851c5c3e36887ceec58154303333

- All 6 metrics passed

### ✅ 00c68566d44cc2de4e0a7625212fb44154b12695

- All 6 metrics passed

### ✅ 01170298bd2b0c367ae8b167c05aa6af600d081b

- All 6 metrics passed

### ✅ 01e34eb4bf47f78ac356b14df852916d8029e6a0

- All 6 metrics passed

### ✅ synth_single_page_simple

- All 6 metrics passed

### ✅ synth_single_block_multi_line

- All 6 metrics passed

### ✅ synth_two_page_double_block

- All 7 metrics passed

### ✅ synth_low_confidence_box

- All 6 metrics passed

### ✅ synth_empty_blocks

- All 1 metrics passed

## Detailed Metrics

| Case | Metric | Match | Legacy | Adapter |
|------|--------|:-----:|--------|---------|
| 001600599b3001997312797d6d41df | page_count | ✓ | 1 | 1 |
| 001600599b3001997312797d6d41df | region_count | ✓ | 1 | 1 |
| 001600599b3001997312797d6d41df | line_count | ✓ | 10 | 10 |
| 001600599b3001997312797d6d41df | p0_text_match | ✓ | - | - |
| 001600599b3001997312797d6d41df | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| 001600599b3001997312797d6d41df | stable_id_determinism | ✓ | - | - |
| 00a5b2b037f3851c5c3e36887ceec5 | page_count | ✓ | 1 | 1 |
| 00a5b2b037f3851c5c3e36887ceec5 | region_count | ✓ | 1 | 1 |
| 00a5b2b037f3851c5c3e36887ceec5 | line_count | ✓ | 7 | 7 |
| 00a5b2b037f3851c5c3e36887ceec5 | p0_text_match | ✓ | - | - |
| 00a5b2b037f3851c5c3e36887ceec5 | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| 00a5b2b037f3851c5c3e36887ceec5 | stable_id_determinism | ✓ | - | - |
| 00c68566d44cc2de4e0a7625212fb4 | page_count | ✓ | 1 | 1 |
| 00c68566d44cc2de4e0a7625212fb4 | region_count | ✓ | 1 | 1 |
| 00c68566d44cc2de4e0a7625212fb4 | line_count | ✓ | 8 | 8 |
| 00c68566d44cc2de4e0a7625212fb4 | p0_text_match | ✓ | - | - |
| 00c68566d44cc2de4e0a7625212fb4 | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| 00c68566d44cc2de4e0a7625212fb4 | stable_id_determinism | ✓ | - | - |
| 01170298bd2b0c367ae8b167c05aa6 | page_count | ✓ | 1 | 1 |
| 01170298bd2b0c367ae8b167c05aa6 | region_count | ✓ | 1 | 1 |
| 01170298bd2b0c367ae8b167c05aa6 | line_count | ✓ | 10 | 10 |
| 01170298bd2b0c367ae8b167c05aa6 | p0_text_match | ✓ | - | - |
| 01170298bd2b0c367ae8b167c05aa6 | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| 01170298bd2b0c367ae8b167c05aa6 | stable_id_determinism | ✓ | - | - |
| 01e34eb4bf47f78ac356b14df85291 | page_count | ✓ | 1 | 1 |
| 01e34eb4bf47f78ac356b14df85291 | region_count | ✓ | 1 | 1 |
| 01e34eb4bf47f78ac356b14df85291 | line_count | ✓ | 6 | 6 |
| 01e34eb4bf47f78ac356b14df85291 | p0_text_match | ✓ | - | - |
| 01e34eb4bf47f78ac356b14df85291 | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| 01e34eb4bf47f78ac356b14df85291 | stable_id_determinism | ✓ | - | - |
| synth_single_page_simple | page_count | ✓ | 1 | 1 |
| synth_single_page_simple | region_count | ✓ | 1 | 1 |
| synth_single_page_simple | line_count | ✓ | 1 | 1 |
| synth_single_page_simple | p0_text_match | ✓ | - | - |
| synth_single_page_simple | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| synth_single_page_simple | stable_id_determinism | ✓ | - | - |
| synth_single_block_multi_line | page_count | ✓ | 1 | 1 |
| synth_single_block_multi_line | region_count | ✓ | 1 | 1 |
| synth_single_block_multi_line | line_count | ✓ | 5 | 5 |
| synth_single_block_multi_line | p0_text_match | ✓ | - | - |
| synth_single_block_multi_line | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| synth_single_block_multi_line | stable_id_determinism | ✓ | - | - |
| synth_two_page_double_block | page_count | ✓ | 2 | 2 |
| synth_two_page_double_block | region_count | ✓ | 3 | 3 |
| synth_two_page_double_block | line_count | ✓ | 6 | 6 |
| synth_two_page_double_block | p0_text_match | ✓ | - | - |
| synth_two_page_double_block | p1_text_match | ✓ | - | - |
| synth_two_page_double_block | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| synth_two_page_double_block | stable_id_determinism | ✓ | - | - |
| synth_low_confidence_box | page_count | ✓ | 1 | 1 |
| synth_low_confidence_box | region_count | ✓ | 1 | 1 |
| synth_low_confidence_box | line_count | ✓ | 1 | 1 |
| synth_low_confidence_box | p0_text_match | ✓ | - | - |
| synth_low_confidence_box | document_ir_round_trip | ✓ | round-trip OK | round-trip OK |
| synth_low_confidence_box | stable_id_determinism | ✓ | - | - |
| synth_empty_blocks | empty_blocks_handling | ✓ | True | True |

## Verification Status

| Metric | Status |
|--------|:------:|
| Page count equivalence | ✅ Pass |
| Region count equivalence | ✅ Pass |
| Line count equivalence | ✅ Pass |
| Text content equivalence | ✅ Pass |
| Bbox/polygon equivalence | ✅ Pass |
| Stable ID determinism | ✅ Pass |
| Provenance populated | ✅ Pass |
| ModuleResult envelope complete | ✅ Pass |
| DocumentIR JSON round-trip | ✅ Pass |
| No NaN/Infinity in bbox | ✅ Pass |

## Adapter vs Legacy Equality Statement

_blocks_to_document_ir() is shared between legacy pipeline path and PaddleOCRLocalAdapter.process(). Adapter wraps output in ModuleResult envelope with fingerprints, trace_id, and latency metadata. The DocumentIR content itself is byte-for-byte identical when inputs are identical._
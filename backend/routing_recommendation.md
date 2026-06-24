# Pipeline Position Validation: Code Language Noise Cleaning Layer

## Pipeline Overview (Current)

```
normalize_text → layout_reconstruction → ... → structure_freeze → split → match
    → normalize_schema → [code_language_noise_clean] → code_structure_reconstruct
    → classify_questions → batch_validation → repair (AI) → review
```

## Three Placement Options Evaluated

### Option A: After normalize_schema (current) — ✅ RECOMMENDED

```
normalize_schema → noise_clean → code_structure_reconstruct
```

**Advantages:**
- **Question-level context**: Operates on parsed question dicts with a clean `stem` field, which represents a single self-contained question. The transition zone detection (nat-lang → code) is inherently a question-level concept.
- **No interference with option parsing**: `structure_freeze` (option detection) and `split` (question boundary detection) have already completed on raw blocks. Noise removal cannot shift option boundaries or break question splitting.
- **Pre-filter for code_structure_reconstruct**: Removes OCR artifacts before the LLM-based code reconstruction stage, reducing false-positive LLM calls. The stress tests confirmed 0 false positives in this position.
- **Clean upgrade path**: Zero changes to earlier pipeline stages. Addition is fully toggled by `enable_code_language_noise_clean` with no cascading effects.
- **All downstream stages benefit**: AI repair, classification, and validation all receive cleaner input.

**Disadvantages:**
- Noise removal only applies to question stems, not to raw OCR block text (which is never used downstream after normalize_schema).
- Cannot fix noise in question options (options are seldom affected by code transition noise in practice).

### Option B: Before normalize_schema (pre-question)

```
structure_freeze → split → match → [noise_clean] → normalize_schema
```

**Disadvantages:**
- Operates on raw concatenated block text, NOT on individual question stems. The noise layer's transition-zone detection assumes question-level boundaries.
- Risk of modifying non-stem text (prose between questions, metadata) that downstream stages rely on.
- `normalize_schema` already strips OCR artifacts during its own cleaning pass — this would duplicate effort.
- Not recommended.

### Option C: Dual-phase split

```
Phase 1 (raw blocks, high recall) → structure_freeze → ... → normalize_schema
    → Phase 2 (question stems, high precision) → code_structure_reconstruct
```

**Disadvantages:**
- Adds complexity with marginal benefit. Phase 1 on raw blocks cannot use question-level context and would need different patterns (broader, risking FP).
- Phase 2 (current implementation) already achieves 0 FP / 0 FN in stress testing.
- Management of two clean phases, two sets of config options, two sets of metrics — not justified by the expected yield.

## Verdict: Option A (current position) is optimal

| Criterion | Option A | Option B | Option C |
|-----------|----------|----------|----------|
| Question-level context | ✅ Full | ❌ Block-level only | ✅ Phase 2 |
| No option-boundary risk | ✅ Safe | ❌ Risk of drift | ✅ Phase 2 |
| Reduces downstream LLM calls | ✅ Pre-filters | ⚠️ Partial | ✅ Full |
| Implementation complexity | Low (1 stage) | Low (1 stage) | High (2 stages) |
| Toggle-able | ✅ Yes | ✅ Yes | ⚠️ Partial |
| False positive risk | ✅ None measured | ⚠️ Higher | ✅ Low |

## Recommendation

**Keep the current position** (`normalize_schema → code_language_noise_clean → code_structure_reconstruct`).

A dual-phase split would only be warranted if field data shows significant noise in raw OCR blocks that does not reach question stems — which is not the case for the targeted `(1> / (>C / C>` noise family, as these always appear at the code transition boundary within a stem.

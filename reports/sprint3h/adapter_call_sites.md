# Adapter Call Site Inventory — commit cc452bb

## Summary

| Object | Status | Prod Files | Test Files |
|--------|--------|-----------|-----------|
| DocumentIR | INTEGRATED | 8 | 13 |
| ModuleResult | NOT_INTEGRATED | 4 | 2 |
| OcrAdapter | NOT_INTEGRATED | 1 | 1 |
| DocumentTransformAdapter | NOT_INTEGRATED | 1 | 1 |
| OCRRequest | NOT_INTEGRATED | 2 | 2 |
| AdapterRegistry | NOT_INTEGRATED | 1 | 2 |
| AdapterSelector | NOT_INTEGRATED | 1 | 1 |
| AdapterCapabilities | NOT_INTEGRATED | 2 | 2 |
| CircuitBreaker | NOT_INTEGRATED | 0 | 0 |
| BenchmarkRunner | NOT_INTEGRATED | 0 | 0 |

## Critical Finding

Only `DocumentIR` is wired into the production pipeline. The rest of commit cc452bb
(ModuleResult envelope, OcrAdapter protocol, AdapterRegistry/Selector, OCRRequest,
CircuitBreaker, BenchmarkRunner) exist as pure definitions — they are tested but
never instantiated or called from any production entry point.

## Legacy private field usage

- `dt_polys`, `rec_texts` — referenced in `ocr_adapter.py` (acceptable as it wraps
  legacy PaddleOCR output into DocumentIR)
- `errorMsg`, `layoutParsingResults` — in `paddleocr_vl_client.py` (boundary with VL API)

## Recommendation

1. Add `ADAPTER_SELECTION_MODE` env var (legacy | shadow | adapter)
2. Wire AdapterSelector into the OCR call path in pipeline_orchestrator
3. Add CircuitBreaker to runtime config for production use

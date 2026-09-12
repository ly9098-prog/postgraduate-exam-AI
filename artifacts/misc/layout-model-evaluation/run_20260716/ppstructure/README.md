# PP-StructureV3 Baseline

## Overview
Zero-shot evaluation of PaddleOCR PP-StructureV3 layout analysis on the ds_sc.pdf dataset (28 diagram pages from data structure exam questions).

## Models Tested

### 1. CDLA Layout Model (`picodet_lcnet_x1_0_fgd_layout_cdla_infer`)
- Chinese document layout analysis (10 categories)
- ✅ Best available zero-shot model for this dataset

### 2. PubLayNet Layout Model (`picodet_lcnet_x1_0_fgd_layout_infer`)
- English academic paper layout (5 categories: text, title, list, table, figure)
- ❌ Worse performance on Chinese exam papers

## Key Findings

| Metric | Value |
|--------|-------|
| Pages with figure detection | 3/28 (10.7%) |
| Pages detected as text-only | 18/28 (64.3%) |
| Layout inference time | ~0.12s per page |
| Full PPStructure time | ~1.5s per page |

### CDLA Label Distribution (28 pages)
- text: 29 regions
- title: 27 regions
- equation: 5 regions (small inline formulas)
- header: 4 regions
- figure: 3 regions (pages 369, 378, 379)
- reference: 2 regions
- footer: 1 region

### Critical Gap
The CDLA model fails to detect diagram regions for 25 of 28 pages that visual-v2 identified as needing image crops. Diagrams such as adjacency lists (p371), B+ trees (p380), and BST variations are classified as "text" because the model's training data (Chinese document layout) treats these as part of the text flow.

## Output Files
- `raw/cdla_layout_results.json` — Full per-page CDLA results
- `raw/publaynet_layout_results.json` — PubLayNet comparison
- `overlays/` — Visual overlays for CDLA figure detections
- `visual/` — Rendered page images

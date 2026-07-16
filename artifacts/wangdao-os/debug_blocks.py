"""Debug pipeline: save normalized blocks to file."""
import asyncio
import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, '/home/lmh/projects/postgraduate-ai/backend')
os.chdir('/home/lmh/projects/postgraduate-ai/backend')
os.environ['APP_ENV'] = 'development'
os.environ['OCR_ENABLED'] = 'true'
os.environ['OCR_USE_GPU'] = 'false'
os.environ['OCR_MAX_WORKERS'] = '1'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///./postgraduate.db'

logging.basicConfig(level=logging.WARNING)

from app.core.database import init_db


async def main():
    await init_db()

    pdf_path = '/home/lmh/projects/postgraduate-ai/ocr_test/import/ds_sc.pdf'
    fd, tmp_path = tempfile.mkstemp(prefix='debug_blocks_', suffix='.pdf')
    try:
        with os.fdopen(fd, 'wb') as f:
            with open(pdf_path, 'rb') as src:
                f.write(src.read())

        from app.features.pipeline_orchestrator import _ocr_scanned_pdf

        # Get OCR blocks
        raw_blocks = _ocr_scanned_pdf(tmp_path, page_start=1, page_end=10)
        print(f'OCR blocks: {len(raw_blocks)}')
        for b in raw_blocks:
            print(f'\n--- Page {b["page"]} ---')
            print(b["text"])

        # Normalize
        from app.features.text_normalizer import ImportTextNormalizer
        normalizer = ImportTextNormalizer()
        normalized = normalizer.normalize(raw_blocks)

        print(f'\n\nNormalized blocks: {len(normalized)}')
        for b in normalized:
            nt = b.get('normalized_text', '')
            print(f'\n--- Page {b["page"]} ---')
            print(repr(nt[:500]))

        # Run boundary detection
        from app.features.question_splitter import _find_question_boundaries

        # Build full text like splitter does
        parts = []
        page_map = []
        pos = 0
        for b in normalized:
            text = b.get('normalized_text', '')
            parts.append(text)
            pos += len(text) + 1
        full_text = '\n'.join(parts)

        print(f'\n\nFull text ({len(full_text)} chars):')
        print('='*60)
        print(full_text)
        print('='*60)

        boundaries = _find_question_boundaries(full_text)
        print(f'\nBoundaries found: {len(boundaries)}')
        for num, pos in boundaries:
            line_start = full_text.rfind('\n', 0, pos) + 1 if pos > 0 else 0
            line_end = full_text.find('\n', pos)
            line = full_text[line_start:line_end] if line_end > 0 else full_text[line_start:line_start+100]
            print(f'  Q{num} at pos {pos}: "{line.strip()[:90]}"')

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


if __name__ == '__main__':
    asyncio.run(main())

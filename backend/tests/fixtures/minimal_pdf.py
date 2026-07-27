"""Minimal PDF generation for test fixtures.

All PDF-dependent tests should use these helpers instead of hardcoding
``/tmp/fake.pdf`` paths that don't exist.
"""
from __future__ import annotations


def _pdf_obj(content: bytes) -> bytes:
    return content + b"\nendobj\n"


def _pdf_stream(content: bytes) -> bytes:
    data = content
    return b"stream\n" + data + b"\nendstream\n"


def make_minimal_pdf(
    *,
    page_count: int = 1,
    text: str = "Hello, world",
    with_page_breaks: bool = False,
) -> bytes:
    """Generate a minimal valid PDF with *page_count* pages.

    Each page contains simple text. The output is a valid PDF that
    PyMuPDF (fitz) and other PDF libraries can open.

    Args:
        page_count: Number of pages (default 1).
        text: Text to display on each page.
        with_page_breaks: If True, each page starts on a new PDF object.

    Returns:
        Bytes of a valid PDF document.
    """
    pages = []
    for i in range(page_count):
        page_text = text if not with_page_breaks else f"{text} — page {i+1}"
        pages.append(
            b"q\nBT\n"
            b"/F1 12 Tf\n"
            b"100 700 Td\n"
            b"(" + page_text.encode("ascii", errors="replace") + b") Tj\n"
            b"ET\nQ"
        )

    objects: list[bytes] = []

    # Catalog
    catalog = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>"
    objects.append(catalog)

    # Pages tree
    page_refs = "".join(f"{3 + i*2} 0 R " for i in range(page_count)).strip()
    pages_obj = (
        b"2 0 obj\n<< /Type /Pages /Kids ["
        + page_refs.encode()
        + b"] /Count "
        + str(page_count).encode()
        + b" >>"
    )
    objects.append(pages_obj)

    # Font (simple PDF built-in font)
    font = b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects.append(font)

    # ProcSet
    procset = b"5 0 obj\n<< /ProcSet [/PDF /Text] >>"
    objects.append(procset)

    for i, page_content in enumerate(pages):
        obj_num = 3 + i * 2
        content_obj_num = obj_num + 1

        # Page object
        page_obj = (
            f"{obj_num} 0 obj\n".encode()
            + b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            + f" /Contents {content_obj_num} 0 R".encode()
            + b" /Resources << /Font << /F1 4 0 R >> /ProcSet 5 0 R >>"
            + b" >>"
        )
        objects.append(page_obj)

        # Content stream
        content_obj = (
            f"{content_obj_num} 0 obj\n".encode()
            + b"<< /Length " + str(len(page_content)).encode() + b" >>\n"
            + _pdf_stream(page_content)
        )
        objects.append(content_obj)

    result = b"%PDF-1.4\n"
    offsets: list[int] = []
    for obj_data in objects:
        offsets.append(result.find(b"obj") if result else 0)
        result += obj_data + b"\n"

    # Cross-reference table
    xref_offset = len(result)
    result += b"xref\n"
    result += f"0 {len(objects) + 1}\n".encode()
    result += b"0000000000 65535 f \n"
    for offset in offsets:
        result += f"{offset:010d} 00000 n \n".encode()

    result += b"trailer\n"
    result += (
        b"<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
    )
    result += b"startxref\n"
    result += str(xref_offset).encode() + b"\n"
    result += b"%%EOF\n"

    return result


@pytest.fixture  # noqa: F821
def minimal_pdf_bytes() -> bytes:
    """Return bytes of a minimal 1-page PDF."""
    return make_minimal_pdf(page_count=1)


@pytest.fixture  # noqa: F821
def minimal_pdf_path(minimal_pdf_bytes, tmp_path) -> str:
    """Write a minimal 1-page PDF to a temp file and return its path."""
    p = tmp_path / "test.pdf"
    p.write_bytes(minimal_pdf_bytes)
    return str(p)


@pytest.fixture  # noqa: F821
def multipage_pdf_path(tmp_path) -> str:
    """Write a multi-page PDF (5 pages) to a temp file and return its path."""
    p = tmp_path / "test_5p.pdf"
    p.write_bytes(make_minimal_pdf(page_count=5))
    return str(p)


@pytest.fixture  # noqa: F821
def large_pdf_path(tmp_path) -> str:
    """Write a 30-page PDF for chunk testing."""
    p = tmp_path / "test_30p.pdf"
    p.write_bytes(make_minimal_pdf(page_count=30))
    return str(p)

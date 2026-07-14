"""Minimal PDF generation for test fixtures.

All PDF-dependent tests should use these helpers instead of hardcoding
``/tmp/fake.pdf`` paths that don't exist.
"""
from __future__ import annotations


def make_minimal_pdf(
    *,
    page_count: int = 1,
    text: str = "Hello, world",
) -> bytes:
    """Generate a minimal valid PDF with *page_count* pages.

    Each page contains simple ASCII text. The output is a valid PDF that
    PyMuPDF (fitz) and other PDF libraries can open.

    Args:
        page_count: Number of pages (default 1).
        text: Text to display on each page.

    Returns:
        Bytes of a valid PDF document.
    """
    # Object numbering:
    # 1: Catalog
    # 2: Pages tree
    # 3: Font
    # 4... : alternating Page + ContentStream per page
    next_obj = 4

    def _obj(n: int, body: bytes) -> bytes:
        return f"{n} 0 obj\n".encode() + body + b"\nendobj\n"

    def _stream(data: bytes) -> bytes:
        return (
            b"<< /Length "
            + str(len(data)).encode()
            + b" >>\nstream\n"
            + data
            + b"\nendstream"
        )

    objects: list[bytes] = []

    # 1: Catalog
    objects.append(_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"))

    # 2: Pages tree
    page_ref_nums = []
    for i in range(page_count):
        page_ref_nums.append(next_obj)
        next_obj += 2  # page + content per page
    kids = " ".join(f"{n} 0 R" for n in page_ref_nums)
    pages_body = (
        b"<< /Type /Pages /Kids [" + kids.encode() + b"] /Count "
        + str(page_count).encode() + b" >>"
    )
    objects.append(_obj(2, pages_body))

    # 3: Font
    objects.append(
        _obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    )

    # 4+: Pages and content streams
    for i in range(page_count):
        page_text = text if page_count == 1 else f"{text} -- page {i+1}"

        stream_data = (
            b"q\nBT\n/F1 12 Tf\n100 700 Td\n("
            + page_text.encode("ascii", errors="replace")
            + b") Tj\nET\nQ"
        )

        page_obj_num = 4 + i * 2
        content_obj_num = page_obj_num + 1

        page_body = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            + f" /Contents {content_obj_num} 0 R".encode()
            + b" /Resources << /Font << /F1 3 0 R >> >> >>"
        )
        objects.append(_obj(page_obj_num, page_body))
        objects.append(_obj(content_obj_num, _stream(stream_data)))

    # Build the file
    result = b"%PDF-1.4\n"
    offsets = [0] * (next_obj + 1)  # 1-indexed by obj number
    for obj_data in objects:
        line = obj_data
        obj_num = int(line.split(b" ")[0])
        offsets[obj_num] = len(result)
        result += line + b"\n"

    xref_offset = len(result)
    total_objs = next_obj  # highest object number used
    result += b"xref\n"
    result += f"0 {total_objs + 1}\n".encode()
    result += b"0000000000 65535 f \n"
    for i in range(1, total_objs + 1):
        result += f"{offsets[i]:010d} 00000 n \n".encode()

    result += b"trailer\n"
    result += (
        b"<< /Size " + str(total_objs + 1).encode() + b" /Root 1 0 R >>\n"
    )
    result += b"startxref\n"
    result += str(xref_offset).encode() + b"\n%%EOF\n"

    return result

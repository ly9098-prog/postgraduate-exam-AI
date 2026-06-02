"""OCR 评测指标：纯标准库实现，无外部依赖。"""
import difflib


def character_error_rate(reference: str, hypothesis: str) -> float:
    """字符错误率：基于 SequenceMatcher 编辑操作计算。"""
    ref = reference.replace("\n", " ").strip()
    hyp = hypothesis.replace("\n", " ").strip()
    if not ref:
        return 0.0 if not hyp else 1.0
    if not hyp:
        return 1.0

    matcher = difflib.SequenceMatcher(None, ref, hyp)
    errors = 0
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace":
            errors += max(i2 - i1, j2 - j1)
        elif op == "delete":
            errors += i2 - i1
        elif op == "insert":
            errors += j2 - j1
    return errors / len(ref)


def line_recall(
    gt_lines: list[str], ocr_lines: list[str], threshold: float = 0.8
) -> tuple[int, int]:
    """行召回：GT 中有多少行在 OCR 输出中找到近似匹配。

    Returns: (matched_count, total_gt_lines)
    """
    if not gt_lines:
        return (0, 0)

    matched = 0
    for gt_line in gt_lines:
        gt_stripped = gt_line.strip()
        if not gt_stripped:
            continue
        for ocr_line in ocr_lines:
            ratio = difflib.SequenceMatcher(
                None, gt_stripped, ocr_line.strip()
            ).ratio()
            if ratio >= threshold:
                matched += 1
                break

    total = sum(1 for line in gt_lines if line.strip())
    return (matched, total)


def line_precision(
    gt_lines: list[str], ocr_lines: list[str], threshold: float = 0.8
) -> tuple[int, int]:
    """行精确率：OCR 输出中有多少行对应 GT 中的真实行。

    Returns: (matched_count, total_ocr_lines)
    """
    if not ocr_lines:
        return (0, 0)

    matched = 0
    for ocr_line in ocr_lines:
        ocr_stripped = ocr_line.strip()
        if not ocr_stripped:
            continue
        for gt_line in gt_lines:
            ratio = difflib.SequenceMatcher(
                None, ocr_stripped, gt_line.strip()
            ).ratio()
            if ratio >= threshold:
                matched += 1
                break

    total = sum(1 for line in ocr_lines if line.strip())
    return (matched, total)


def text_drop_rate(reference: str, hypothesis: str) -> float:
    """文本丢失率：GT 中完全未出现在 OCR 对齐中的字符占比。"""
    ref = reference.replace("\n", " ").strip()
    hyp = hypothesis.replace("\n", " ").strip()
    if not ref:
        return 0.0
    if not hyp:
        return 1.0

    matcher = difflib.SequenceMatcher(None, ref, hyp)
    deleted = 0
    for op, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if op == "delete":
            deleted += i2 - i1
    return deleted / len(ref)

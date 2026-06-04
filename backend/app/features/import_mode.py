"""导入模式定义与策略配置。

三种模式对应不同的文档类型和解析策略：
- AUTO: 自动检测文档类型并选择策略
- BOOK: 教材/辅导书模式（知识点+例题+习题+答案解析）
- EXAM: 试卷/真题模式（题目+答案+解析）
"""

from enum import Enum


class ImportMode(str, Enum):
    AUTO = "auto"
    BOOK = "book"
    EXAM = "exam"


# 每种模式下各阶段的策略参数
MODE_STRATEGIES: dict[ImportMode, dict] = {
    ImportMode.AUTO: {
        "page_classifier_enabled": True,
        "page_classifier_strict": False,
        "filter_knowledge_pages": True,
        "filter_catalog_pages": True,
        "exercise_section_required": False,
        "wangdao_preprocess_auto": True,
        "question_number_gap_tolerance": 10,
        "min_question_confidence": 0.4,
    },
    ImportMode.BOOK: {
        "page_classifier_enabled": True,
        "page_classifier_strict": True,
        "filter_knowledge_pages": True,
        "filter_catalog_pages": True,
        "exercise_section_required": True,
        "wangdao_preprocess_auto": True,
        "question_number_gap_tolerance": 5,
        "min_question_confidence": 0.5,
    },
    ImportMode.EXAM: {
        "page_classifier_enabled": True,
        "page_classifier_strict": False,
        "filter_knowledge_pages": False,
        "filter_catalog_pages": True,
        "exercise_section_required": False,
        "wangdao_preprocess_auto": False,
        "question_number_gap_tolerance": 20,
        "min_question_confidence": 0.3,
    },
}


def detect_import_mode(source_file: str, structure: dict | None = None) -> ImportMode:
    """根据文件名和文档结构自动推断导入模式。"""
    lower = (source_file or "").lower()

    # 文件名启发式
    exam_keywords = ["真题", "试卷", "模拟", "期末", "考试", "exam", "test", "mock"]
    book_keywords = ["王道", "教材", "辅导", "讲义", "wangdao", "textbook"]

    for kw in exam_keywords:
        if kw in lower:
            return ImportMode.EXAM

    for kw in book_keywords:
        if kw in lower:
            return ImportMode.BOOK

    # 结构启发式
    if structure:
        markers = structure.get("section_markers", [])
        has_exercise_marker = any(
            m.get("marker_type") == "exercise_start" for m in markers
        )
        has_knowledge_content = bool(structure.get("content_pages"))

        if has_exercise_marker and has_knowledge_content:
            return ImportMode.BOOK

        mode = structure.get("mode")
        if mode == "SEPARATED" and not has_knowledge_content:
            return ImportMode.EXAM

    return ImportMode.BOOK


def get_strategy(mode: ImportMode) -> dict:
    """获取指定模式的策略配置。"""
    return MODE_STRATEGIES[mode].copy()

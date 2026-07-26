"""Map space_style × question_type to answer-space height in mm.

Each question type gets a baseline height for each space style.
Unrecognized types are treated as subjective (the most conservative).
"""

from __future__ import annotations

from app.features.question_type import (
    QT_FILL_BLANK,
    QT_MULTI_BLANK_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_SUBJECTIVE,
    QT_TRUE_FALSE,
)
from app.schemas.export_task import ExportSpaceStyle

# Heights in mm — the vertical gap reserved after the question content
# for handwritten answers. Choice questions and true/false get zero
# (marking is done on the answer sheet or choices list).
_SPACE_MM: dict[str, dict[str, float]] = {
    ExportSpaceStyle.COMPACT: {
        QT_SINGLE_CHOICE: 0,
        QT_MULTIPLE_CHOICE: 0,
        QT_TRUE_FALSE: 0,
        QT_FILL_BLANK: 8,
        QT_MULTI_BLANK_CHOICE: 0,
        QT_SUBJECTIVE: 30,
    },
    ExportSpaceStyle.STANDARD: {
        QT_SINGLE_CHOICE: 0,
        QT_MULTIPLE_CHOICE: 0,
        QT_TRUE_FALSE: 0,
        QT_FILL_BLANK: 15,
        QT_MULTI_BLANK_CHOICE: 0,
        QT_SUBJECTIVE: 60,
    },
    ExportSpaceStyle.SPACIOUS: {
        QT_SINGLE_CHOICE: 0,
        QT_MULTIPLE_CHOICE: 0,
        QT_TRUE_FALSE: 0,
        QT_FILL_BLANK: 25,
        QT_MULTI_BLANK_CHOICE: 0,
        QT_SUBJECTIVE: 100,
    },
}


def get_answer_space_mm(space_style: str, question_type: str | None) -> float:
    """Return the answer-space height in mm for the given type and style."""
    style_map = _SPACE_MM.get(space_style, _SPACE_MM[ExportSpaceStyle.STANDARD])
    return style_map.get(question_type or "", style_map.get(QT_SUBJECTIVE, 60))

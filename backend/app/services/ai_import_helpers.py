"""AI 辅助导题用到的纯函数辅助逻辑（解析、规整、缺失检测）。"""
import json
import re

from app.models.question_import import QuestionImport

SUBJECT_VALUES = {"math2", "exam408", "english"}
TYPE_VALUES = {"choice", "fill", "subjective"}


def extract_json(text: str) -> dict | None:
    """从 AI 返回中尽量提取 JSON 对象。容忍 markdown 代码块包裹。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    brace = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(1))
        except json.JSONDecodeError:
            pass
    return None


def qi_to_dict(qi: QuestionImport) -> dict:
    return {
        "subject": qi.subject,
        "question_type": qi.question_type,
        "parsed_content": qi.parsed_content,
        "parsed_options": qi.parsed_options,
        "parsed_answer": qi.parsed_answer,
        "parsed_analysis": qi.parsed_analysis,
        "raw_text": (qi.raw_data or {}).get("stem") if qi.raw_data else None,
    }


def normalize_enrich(parsed: dict) -> dict:
    """规整 AI enrich 输出，丢弃异常值。"""
    out: dict = {}
    subject = parsed.get("subject")
    if subject in SUBJECT_VALUES:
        out["subject"] = subject
    qtype = parsed.get("question_type")
    if qtype in TYPE_VALUES:
        out["question_type"] = qtype
    diff = parsed.get("difficulty")
    if isinstance(diff, (int, float)):
        diff = int(diff)
        if 1 <= diff <= 5:
            out["difficulty"] = diff
    kps = parsed.get("knowledge_points")
    if isinstance(kps, list):
        out["knowledge_points"] = [str(k).strip() for k in kps if str(k).strip()]
    chapter = parsed.get("chapter")
    if isinstance(chapter, str) and chapter.strip():
        out["chapter"] = chapter.strip()
    cat = parsed.get("question_category")
    if isinstance(cat, str) and cat.strip():
        out["question_category"] = cat.strip()
    conf = parsed.get("confidence")
    if isinstance(conf, (int, float)):
        out["confidence"] = max(0.0, min(1.0, float(conf)))
    reason = parsed.get("reason")
    if isinstance(reason, str):
        out["reason"] = reason
    return out


def normalize_generated_question(item: dict) -> dict | None:
    subject = item.get("subject")
    if subject not in SUBJECT_VALUES:
        return None
    qtype = item.get("question_type") or "choice"
    if qtype not in TYPE_VALUES:
        qtype = "choice"
    stem = (item.get("stem") or "").strip()
    if len(stem) < 5:
        return None
    options = item.get("options") if isinstance(item.get("options"), dict) else None
    answer = (item.get("answer") or "").strip()
    analysis = (item.get("analysis") or "").strip()
    kps = item.get("knowledge_points")
    if not isinstance(kps, list):
        kps = []
    diff = item.get("difficulty", 3)
    try:
        diff = int(diff)
    except (TypeError, ValueError):
        diff = 3
    diff = max(1, min(5, diff))
    return {
        "subject": subject,
        "question_type": qtype,
        "parsed_content": {"text": stem},
        "parsed_options": options,
        "parsed_answer": answer or None,
        "parsed_analysis": analysis or None,
        "knowledge_points": [str(k).strip() for k in kps if str(k).strip()],
        "difficulty": diff,
    }


def detect_missing(qi: QuestionImport) -> list[str]:
    missing = []
    if not qi.subject:
        missing.append("subject")
    if not qi.question_type:
        missing.append("question_type")
    if not (qi.parsed_content and qi.parsed_content.get("text")):
        missing.append("stem")
    if not qi.parsed_answer:
        missing.append("answer")
    if not qi.parsed_analysis:
        missing.append("analysis")
    return missing

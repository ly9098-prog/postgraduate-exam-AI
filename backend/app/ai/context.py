"""构建传给 AI 的上下文。只传必要信息，不传完整历史。"""


def build_error_context(wrong_question, question, knowledge_points=None) -> dict:
    return {
        "question": {
            "content": question.content,
            "options": question.options,
            "answer": question.answer,
            "knowledge_points": knowledge_points
            if knowledge_points is not None
            else [],
        },
        "user_answer": wrong_question.wrong_answer,
        "error_type": wrong_question.error_type,
        "review_count": wrong_question.review_count,
    }

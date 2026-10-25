function findQuestionIdError(rawQuestions) {
  const seenQuestionIds = new Set()
  const invalidQuestionIds = []
  const duplicateQuestionIds = []
  rawQuestions.forEach((question) => {
    const questionId = Number(question && question.id)
    if (!Number.isInteger(questionId) || questionId <= 0) {
      invalidQuestionIds.push(question && question.id)
      return
    }
    if (seenQuestionIds.has(questionId)) {
      duplicateQuestionIds.push(questionId)
      return
    }
    seenQuestionIds.add(questionId)
  })
  if (invalidQuestionIds.length > 0 || duplicateQuestionIds.length > 0) {
    return { kind: 'invalid_ids', invalidQuestionIds, duplicateQuestionIds }
  }
  return null
}

function findUnsupportedTypeError(rawQuestions, options) {
  const unsupportedQuestions = rawQuestions.filter(question => {
    const questionType = String((question && question.question_type) || '')
    return !options.answerableTypes.has(questionType)
  })
  if (unsupportedQuestions.length === 0) return null
  return {
    kind: 'unsupported_type',
    rejected: unsupportedQuestions.map(question => ({
      id: question && question.id,
      question_type: question && question.question_type,
      subject_id: question && question.subject_id,
    })),
  }
}

function findSubjectScopeError(rawQuestions, options) {
  const canValidateSubjectScope = options.allowedScopeIds.size > 0
  const outOfScopeQuestions = canValidateSubjectScope
    ? rawQuestions.filter(question => {
      const questionSubjectId = Number(question && question.subject_id)
      return !questionSubjectId || !options.allowedScopeIds.has(questionSubjectId)
    })
    : []
  if (outOfScopeQuestions.length === 0) return null
  return {
    kind: 'subject_scope',
    allowedScopeIds: Array.from(options.allowedScopeIds),
    rejected: outOfScopeQuestions.map(question => ({
      id: question && question.id,
      subject_id: question && question.subject_id,
      subject_code: question && question.subject_code,
    })),
  }
}

module.exports = {
  findQuestionIdError,
  findUnsupportedTypeError,
  findSubjectScopeError,
}

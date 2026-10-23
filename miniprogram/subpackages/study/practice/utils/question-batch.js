function buildQuestionRequestParams(options) {
  const mode = options.selectedMode || 'random'
  const params = {
    subject_id: options.subjectId,
    include_children: Boolean(options.selectedSubjectHasChildren && (mode === 'random' || mode === 'smart')),
    count: options.count || 5,
    mode,
    _traceId: options.traceId,
  }
  if (mode === 'sequential') {
    params.exclude_answered = false
    params.use_leitner = false
  } else if (options.launchQuestionIds) {
    params.question_ids = options.launchQuestionIds
    params.exclude_answered = false
    params.use_leitner = false
  } else {
    params.exclude_answered = !options.launchAllowRepeat
    if (!options.launchAllowRepeat) params.no_repeat_days = 30
    params.use_leitner = true
  }
  if (options.launchPlanToken) params.plan_token = options.launchPlanToken
  if (options.launchKnowledgePointId) {
    params.knowledge_point_id = options.launchKnowledgePointId
    if (options.launchIncludeDescendants) params.include_descendants = true
  } else if (options.launchKnowledgePoint) {
    params.knowledge_point = options.launchKnowledgePoint
  }
  return params
}

function validateKnowledgeScope(scope, requestedRootId) {
  const rootId = Number(scope && scope.root_knowledge_point_id)
  const scopeSize = Number(scope && scope.knowledge_point_count)
  return Boolean(
    scope &&
    rootId === Number(requestedRootId) &&
    scope.include_descendants === true &&
    Number.isInteger(scopeSize) &&
    scopeSize >= 1
  )
}

function findQuestionBatchError(rawQuestions, options) {
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
    return {
      kind: 'invalid_ids',
      invalidQuestionIds,
      duplicateQuestionIds,
    }
  }

  const unsupportedQuestions = rawQuestions.filter(question => {
    const questionType = String((question && question.question_type) || '')
    return !options.answerableTypes.has(questionType)
  })
  if (unsupportedQuestions.length > 0) {
    return {
      kind: 'unsupported_type',
      rejected: unsupportedQuestions.map(question => ({
        id: question && question.id,
        question_type: question && question.question_type,
        subject_id: question && question.subject_id,
      })),
    }
  }

  const canValidateSubjectScope = options.allowedScopeIds.size > 0
  const outOfScopeQuestions = canValidateSubjectScope
    ? rawQuestions.filter(question => {
      const questionSubjectId = Number(question && question.subject_id)
      return !questionSubjectId || !options.allowedScopeIds.has(questionSubjectId)
    })
    : []
  if (outOfScopeQuestions.length > 0) {
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
  return null
}

module.exports = {
  buildQuestionRequestParams,
  validateKnowledgeScope,
  findQuestionBatchError,
}

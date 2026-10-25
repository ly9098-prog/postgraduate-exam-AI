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
  return findQuestionIdError(rawQuestions)
    || findUnsupportedTypeError(rawQuestions, options)
    || findSubjectScopeError(rawQuestions, options)
}

module.exports = {
  buildQuestionRequestParams,
  validateKnowledgeScope,
  findQuestionBatchError,
}
const {
  findQuestionIdError,
  findUnsupportedTypeError,
  findSubjectScopeError,
} = require('./question-batch-validation')

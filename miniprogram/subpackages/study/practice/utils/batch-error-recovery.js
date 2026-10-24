/**
 * Map a question batch error to a recovery action (reset message + toast).
 *
 * Pure function — no page state, no wx APIs. Extracted from practice.js
 * _loadQuestions to make the error-to-recovery contract testable.
 */

var ERROR_MESSAGES = {
  invalid_ids: {
    resetMessage: '检测到练习批次题目异常，请重试。若持续出现，请更新后端服务。',
    toastTitle: '练习批次异常，请重试',
    logTag: '[PRACTICE_INVALID_BATCH_QUESTION_IDS]',
  },
  unsupported_type: {
    resetMessage: '检测到当前版本暂不支持作答的题型，请重试或更新后端服务。',
    toastTitle: '题型暂不支持，请重试',
    logTag: '[PRACTICE_UNSUPPORTED_QUESTION_TYPE]',
  },
  subject_scope: {
    resetMessage: '检测到题目科目异常，请重试。若持续出现，请更新后端服务。',
    toastTitle: '题目科目异常，请重试',
    logTag: '[PRACTICE_SUBJECT_SCOPE_MISMATCH]',
  },
}

/**
 * Resolve a batch error to a recovery action, or null if no error.
 *
 * Returns { kind, resetMessage, toastTitle, logTag, logDetail } or null.
 */
function resolveBatchErrorRecovery(batchError, context) {
  if (!batchError || !batchError.kind) return null
  var config = ERROR_MESSAGES[batchError.kind]
  if (!config) return null

  var logDetail = {
    selectedSubjectId: Number(context.subjectId),
    traceId: context.traceId || '',
  }

  if (batchError.kind === 'invalid_ids') {
    logDetail.invalidQuestionIds = batchError.invalidQuestionIds
    logDetail.duplicateQuestionIds = batchError.duplicateQuestionIds
  } else if (batchError.kind === 'unsupported_type') {
    logDetail.rejected = batchError.rejected
  } else if (batchError.kind === 'subject_scope') {
    logDetail.includeChildren = Boolean(context.includeChildren)
    logDetail.allowedScopeIds = batchError.allowedScopeIds
    logDetail.rejected = batchError.rejected
  }

  return {
    kind: batchError.kind,
    resetMessage: config.resetMessage,
    toastTitle: config.toastTitle,
    logTag: config.logTag,
    logDetail: logDetail,
  }
}

module.exports = { resolveBatchErrorRecovery, ERROR_MESSAGES }

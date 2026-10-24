/**
 * Build the API submit payload from a submission snapshot.
 *
 * Pure function — extracted from practice.js doSubmit.
 */
function buildSubmitPayload(submission, traceId) {
  return {
    answers: submission.answers,
    skipped_question_ids: submission.skippedQuestionIds,
    session: submission.session,
    _traceId: submission.traceId || traceId || '',
    batch_token: submission.batchToken,
  }
}

/**
 * Classify a submit error as deterministic reject or retryable.
 *
 * Returns true if the error is a deterministic rejection (4xx excluding
 * 401/408/429, or a known conflict/invalid error code).
 */
function isDeterministicReject(error) {
  var statusCode = Number(error && error.statusCode) || 0
  var errorCode = String((error && error.code) || '')
  return (
    errorCode === 'PRACTICE_SUBMISSION_CONFLICT' ||
    errorCode === 'PRACTICE_QUESTION_VERSION_CONFLICT' ||
    errorCode === 'PRACTICE_BATCH_INVALID' ||
    errorCode === 'PRACTICE_PAYLOAD_INVALID' ||
    (statusCode >= 400 && statusCode < 500 && ![401, 408, 429].includes(statusCode))
  )
}

/**
 * Map an error code to a rejection dialog { title, content }.
 *
 * Returns a default message for unrecognized deterministic rejects.
 */
var REJECT_MESSAGES = {
  PRACTICE_SUBMISSION_CONFLICT: {
    title: '交卷标识冲突',
    content: '该 request_id 已对应另一份提交。为避免结果串单，本次内容不会继续重试，请退出后重新开始。',
  },
  PRACTICE_QUESTION_VERSION_CONFLICT: {
    title: '题目版本无法恢复',
    content: '本组练习中有题目的历史版本无法恢复。为避免使用错误版本判题，本次提交已停止，请返回重新获取题目。',
  },
  PRACTICE_BATCH_INVALID: {
    title: '练习批次已失效',
    content: '本次题目批次已过期或与提交内容不一致。为避免串题，请退出后重新获取题目。',
  },
}

function resolveRejectMessage(errorCode) {
  var code = String(errorCode || '')
  var msg = REJECT_MESSAGES[code]
  if (msg) return { title: msg.title, content: msg.content }
  return {
    title: '交卷内容未通过校验',
    content: '服务器已明确拒绝本次提交，继续重试相同内容不会成功。请退出后重新开始。',
  }
}

module.exports = {
  buildSubmitPayload,
  isDeterministicReject,
  resolveRejectMessage,
}

/**
 * Build a submission snapshot object from doSubmit intermediate values.
 *
 * Pure function — no page state. Extracted from practice.js doSubmit
 * to make the snapshot contract testable.
 */
function buildSubmissionSnapshot(options) {
  return {
    requestId: options.requestId,
    traceId: options.traceId || '',
    answers: options.answers,
    skippedQuestionIds: options.skippedQuestionIds.slice(),
    partialQuestionIds: options.partialQuestionIds.slice(),
    session: options.session,
    duration: options.duration,
    total: options.total,
    unanswered: options.unanswered,
    selectedSubjectId: options.selectedSubjectId,
    selectedSubjectName: options.selectedSubjectName,
    comboCount: options.comboCount,
    answerMap: Object.assign({}, options.answerMap),
    answeredFlags: Object.assign({}, options.answeredFlags),
    recoveryQuestions: options.recoveryQuestions,
    batchToken: options.batchToken || '',
    knowledgeScope: options.knowledgeScope
      ? Object.assign({}, options.knowledgeScope)
      : null,
    retryBlocked: false,
    serverAccepted: false,
    pendingPersisted: false,
    keepPendingUntilResult: false,
  }
}

module.exports = { buildSubmissionSnapshot }

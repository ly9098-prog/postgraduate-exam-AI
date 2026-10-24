/**
 * Build the answers array and session object for practice submission.
 *
 * Pure functions — extracted from practice.js doSubmit.
 */

/**
 * Build the answers payload from completed questions and answer/time maps.
 */
function buildSubmitAnswers(options) {
  var completedQuestions = options.completedQuestions || []
  var answerMap = options.answerMap || {}
  var questionTimeMap = options.questionTimeMap || {}
  var recommendationRequestId = options.recommendationRequestId || null

  return completedQuestions.map(function(q) {
    return {
      question_id: q.id,
      user_answer: answerMap[String(q.id)] || '',
      used_time: questionTimeMap[String(q.id)] || 0,
      request_id: recommendationRequestId,
    }
  })
}

/**
 * Build the session metadata object.
 */
function buildSubmitSession(options) {
  return {
    request_id: options.requestId,
    subject_id: options.subjectId,
    mode: options.mode || 'random',
    started_at: new Date(options.startedAtMs || (options.finishedAtMs - options.duration * 1000)).toISOString(),
    finished_at: new Date(options.finishedAtMs).toISOString(),
    duration_sec: options.duration,
    question_count: options.total,
    answered_count: options.answeredCount,
    status: 'completed',
  }
}

module.exports = { buildSubmitAnswers, buildSubmitSession }

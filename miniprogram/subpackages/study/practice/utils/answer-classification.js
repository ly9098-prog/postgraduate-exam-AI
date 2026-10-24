/**
 * Classify questions into answered, partial, and skipped sets.
 *
 * Pure function — extracted from practice.js doSubmit to make the
 * answer classification contract testable without a page instance.
 */

function classifyAnswers(options) {
  var questions = options.questions || []
  var answerMap = options.answerMap || {}
  var answeredFlags = options.answeredFlags
  var total = questions.length

  var answeredCount = 0
  var completedQuestions = []
  var partialQuestionIds = []
  var skippedQuestionIds = []

  for (var i = 0; i < questions.length; i++) {
    var q = questions[i]
    var key = String(q.id)
    var isAnswered = answeredFlags[key]
    if (isAnswered) answeredCount++
    if (isAnswered) {
      completedQuestions.push(q)
    } else if (options.isMultiBlank(q) && answerMap[key]) {
      partialQuestionIds.push(q.id)
    }
    if (!isAnswered) {
      skippedQuestionIds.push(q.id)
    }
  }

  var unanswered = total - answeredCount

  return {
    answeredFlags: answeredFlags,
    answeredCount: answeredCount,
    completedQuestions: completedQuestions,
    partialQuestionIds: partialQuestionIds,
    skippedQuestionIds: skippedQuestionIds,
    unanswered: unanswered,
    total: total,
  }
}

module.exports = { classifyAnswers }

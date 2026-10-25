const {
  buildGroupReviews,
  buildGroupResult,
} = require('./group-submission')

function buildReviewSubmission(input) {
  return buildGroupReviews({
    groupQuestions: input.groupQuestions,
    answers: input.answers,
    isQuestionAnswered: input.isQuestionAnswered,
    getRequestId: input.getRequestId,
  })
}

function buildGroupResults(input, reviews, results) {
  return input.groupQuestions.map(question => buildGroupResult({
    question,
    results,
    reviews,
    answers: input.answers,
    isQuestionAnswered: input.isQuestionAnswered,
    enrichForResult: input.enrichForResult,
    failureNeedsRefresh: input.failureNeedsRefresh,
  }))
}

module.exports = {
  buildReviewSubmission,
  buildGroupResults,
}

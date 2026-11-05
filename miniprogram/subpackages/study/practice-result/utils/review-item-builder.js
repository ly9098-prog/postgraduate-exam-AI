/**
 * Pure helpers for building review items, extracted from practice-result/index.js.
 *
 * These depend on module-level helpers from the page file (normalizeReviewStatus,
 * pad2, getQuestionTitle, formatAnswerPreview, formatMathPreviewText, normalizeKpList)
 * which are passed in via the helpers parameter to avoid circular requires.
 */

var errorDiagnosis = require('../../utils/error-diagnosis')

/**
 * Build a review item from question, result, and answer objects.
 */
function buildReviewItem(question, result, answer, index, helpers) {
  var h = helpers || {}
  var questionId =
    question.id != null ? question.id :
    question.question_id != null ? question.question_id :
    question.questionId != null ? question.questionId :
    result.question_id != null ? result.question_id :
    result.questionId != null ? result.questionId :
    index + 1
  var normalizedDiagnosis = errorDiagnosis.normalizeDiagnosis(result.error_diagnosis != null ? result.error_diagnosis : result.errorDiagnosis)
  var isCorrectRaw =
    result.is_correct != null ? result.is_correct :
    result.isCorrect != null ? result.isCorrect :
    answer.is_correct != null ? answer.is_correct :
    answer.isCorrect != null ? answer.isCorrect :
    false
  var status = h.normalizeReviewStatus(
    Object.assign({}, answer || {}, result || {}),
    !!isCorrectRaw
  )
  var referenceOnly = result.reference_only === true || result.referenceOnly === true
  if (referenceOnly) status = 'partial'
  var kpList = h.normalizeKpList(
    result.knowledge_points != null ? result.knowledge_points :
    result.knowledgePoints != null ? result.knowledgePoints :
    question.knowledge_points != null ? question.knowledge_points :
    question.knowledgePoints
  )
  return {
    questionId: questionId,
    questionVersionId: result.question_version_id != null ? result.question_version_id : (result.questionVersionId != null ? result.questionVersionId : (question.question_version_id != null ? question.question_version_id : (question.questionVersionId != null ? question.questionVersionId : null))),
    wrongQuestionId: result.wrong_question_id != null ? result.wrong_question_id : (result.wrongQuestionId != null ? result.wrongQuestionId : null),
    displayIndex: h.pad2(index + 1),
    title: h.getQuestionTitle(question) || ('第 ' + (index + 1) + ' 题'),
    status: status,
    statusLabel: referenceOnly ? '参考自查' : status,
    isCorrect: status === 'correct',
    isSkipped: status === 'skipped',
    isPartial: status === 'partial',
    userAnswer: h.formatAnswerPreview(answer.user_answer != null ? answer.user_answer : (answer.userAnswer != null ? answer.userAnswer : (result.user_answer != null ? result.user_answer : (result.userAnswer != null ? result.userAnswer : '')))),
    correctAnswer: h.formatAnswerPreview(result.correct_answer != null ? result.correct_answer : (result.correctAnswer != null ? result.correctAnswer : (question.answer != null ? question.answer : ''))),
    analysis: result.analysis != null ? result.analysis : (question.analysis != null ? question.analysis : ''),
    knowledgePoints: kpList,
    knowledgePoint: kpList[0] || '未标注知识点',
    errorDiagnosis: normalizedDiagnosis,
    errorDiagnosisLabel: normalizedDiagnosis ? normalizedDiagnosis.primaryLabel : errorDiagnosis.labelOf('unknown'),
  }
}

/**
 * Normalize a review item from a raw item object.
 */
function normalizeReviewItem(item, index, helpers) {
  var h = helpers || {}
  var normalizedDiagnosis = errorDiagnosis.normalizeDiagnosis(item.errorDiagnosis != null ? item.errorDiagnosis : item.error_diagnosis)
  var isCorrectRaw = item.is_correct != null ? item.is_correct : (item.isCorrect != null ? item.isCorrect : (item.correct != null ? item.correct : false))
  var status = h.normalizeReviewStatus(item, !!isCorrectRaw)
  var referenceOnly = item.reference_only === true || item.referenceOnly === true
  if (referenceOnly) status = 'partial'
  var kpList = h.normalizeKpList(item.knowledge_points != null ? item.knowledge_points : (item.knowledgePoints != null ? item.knowledgePoints : item.knowledgePoint))
  return {
    questionId: item.questionId != null ? item.questionId : (item.question_id != null ? item.question_id : (item.id != null ? item.id : index + 1)),
    questionVersionId: item.questionVersionId != null ? item.questionVersionId : (item.question_version_id != null ? item.question_version_id : null),
    wrongQuestionId: item.wrongQuestionId != null ? item.wrongQuestionId : (item.wrong_question_id != null ? item.wrong_question_id : null),
    displayIndex: item.displayIndex || h.pad2(index + 1),
    title: h.formatMathPreviewText(item.title || h.getQuestionTitle(item)) || ('第 ' + (index + 1) + ' 题'),
    status: status,
    statusLabel: referenceOnly ? '参考自查' : status,
    isCorrect: status === 'correct',
    isSkipped: status === 'skipped',
    isPartial: status === 'partial',
    userAnswer: h.formatAnswerPreview(item.userAnswer != null ? item.userAnswer : (item.user_answer != null ? item.user_answer : (item.wrong_answer != null ? item.wrong_answer : ''))),
    correctAnswer: h.formatAnswerPreview(item.correctAnswer != null ? item.correctAnswer : (item.correct_answer != null ? item.correct_answer : (item.answer != null ? item.answer : ''))),
    analysis: item.analysis != null ? item.analysis : '',
    knowledgePoints: kpList,
    knowledgePoint: item.knowledgePoint || kpList[0] || '未标注知识点',
    errorDiagnosis: normalizedDiagnosis,
    errorDiagnosisLabel: normalizedDiagnosis ? normalizedDiagnosis.primaryLabel : errorDiagnosis.labelOf(item.error_type || 'unknown'),
  }
}

module.exports = { buildReviewItem, normalizeReviewItem }

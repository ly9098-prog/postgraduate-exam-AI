var { normalizeBlankOptionList } = require('./question-adapter-options')
var { getQuestionOptions, getBlankOptionGroups } = require('./question-adapter-groups')
var { normalizeBlankAnswer, serializeBlankAnswer, isMultiBlankChoice, isMultiBlankMultipleChoice, isQuestionAnswered, buildAnsweredFlags, countAnswered, applyAnsweredFlags, computeAnsweredCount, getCorrectAnswer, isAnswerCorrect } = require('./question-adapter-answers')
var { enrichBlankOptionGroups, enrichBlankOptionGroupsReadonly, buildOptionListFromFlags, buildOptionList, buildOptionListReadonly } = require('./question-adapter-views')
var { getQuestionImages, getEmbeddedImageUrls, computeExtraImages, getQuestionPrefetchUrls } = require('./question-adapter-images')

module.exports = {
  normalizeBlankAnswer: normalizeBlankAnswer,
  normalizeBlankOptionList: normalizeBlankOptionList,
  getQuestionOptions: getQuestionOptions,
  getBlankOptionGroups: getBlankOptionGroups,
  enrichBlankOptionGroups: enrichBlankOptionGroups,
  enrichBlankOptionGroupsReadonly: enrichBlankOptionGroupsReadonly,
  serializeBlankAnswer: serializeBlankAnswer,
  isMultiBlankChoice: isMultiBlankChoice,
  isMultiBlankMultipleChoice: isMultiBlankMultipleChoice,
  isQuestionAnswered: isQuestionAnswered,
  buildAnsweredFlags: buildAnsweredFlags,
  countAnswered: countAnswered,
  applyAnsweredFlags: applyAnsweredFlags,
  computeAnsweredCount: computeAnsweredCount,
  buildOptionListFromFlags: buildOptionListFromFlags,
  buildOptionList: buildOptionList,
  buildOptionListReadonly: buildOptionListReadonly,
  getCorrectAnswer: getCorrectAnswer,
  isAnswerCorrect: isAnswerCorrect,
  getQuestionImages: getQuestionImages,
  getEmbeddedImageUrls: getEmbeddedImageUrls,
  computeExtraImages: computeExtraImages,
  getQuestionPrefetchUrls: getQuestionPrefetchUrls,
}

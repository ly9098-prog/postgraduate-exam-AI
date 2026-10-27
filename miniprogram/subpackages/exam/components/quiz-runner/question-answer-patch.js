function appendAnswerPatch(data, q, answerState, questionId, questionAdapter) {
  var answerStateMatches = !!(
    answerState &&
    String(answerState.questionId == null ? '' : answerState.questionId) === questionId
  )
  var blankOptionGroups = answerStateMatches && Array.isArray(answerState.blankOptionGroups)
    ? answerState.blankOptionGroups
    : (Array.isArray(q._blankOptionGroups) ? q._blankOptionGroups : [])
  blankOptionGroups = enrichBlankGroups(q, blankOptionGroups, questionAdapter)
  data._blankOptionGroups = blankOptionGroups
  data._hasBlankOptionGroups = blankOptionGroups.length > 0
  data._isMultiBlankMultiple = q.question_type === 'multi_blank_multiple_choice'
  data._optionList = resolveOptionList(q, answerState, answerStateMatches, blankOptionGroups, questionAdapter)
}

function enrichBlankGroups(q, blankOptionGroups, questionAdapter) {
  if (questionAdapter && typeof questionAdapter.getBlankOptionGroups === 'function') {
    try {
      var rawGroups = blankOptionGroups
      if (!rawGroups.length) rawGroups = questionAdapter.getBlankOptionGroups(q)
      var firstGroup = rawGroups[0]
      var firstOption = firstGroup && Array.isArray(firstGroup.options)
        ? firstGroup.options[0]
        : null
      var needsEnrich = !!(rawGroups.length && (!firstOption || !firstOption._text))
      if (needsEnrich && typeof questionAdapter.enrichBlankOptionGroups === 'function') {
        rawGroups = questionAdapter.enrichBlankOptionGroups(
          rawGroups,
          q._blankAnswer || q.user_answer || ''
        )
      }
      if (rawGroups.length) blankOptionGroups = rawGroups
    } catch (e) {
    }
  }
  return blankOptionGroups
}

function resolveOptionList(q, answerState, answerStateMatches, blankOptionGroups, questionAdapter) {
  var optionList = answerStateMatches && Array.isArray(answerState.optionList)
    ? answerState.optionList
    : (Array.isArray(q._optionList) ? q._optionList : [])
  if (!optionList.length && !blankOptionGroups.length &&
    questionAdapter && typeof questionAdapter.buildOptionListFromFlags === 'function') {
    try {
      var optionSource = q._opts && Object.keys(q._opts).length > 0
        ? q._opts
        : (typeof questionAdapter.getQuestionOptions === 'function'
          ? questionAdapter.getQuestionOptions(q)
          : q.options)
      if (optionSource && typeof optionSource === 'object') {
        var optionKeys = Array.isArray(q._optionKeys)
          ? q._optionKeys
          : Object.keys(optionSource)
        optionList = questionAdapter.buildOptionListFromFlags(
          optionSource,
          optionKeys,
          q._selectedFlags || {}
        )
      }
    } catch (e) {
    }
  }
  return optionList
}

module.exports = appendAnswerPatch

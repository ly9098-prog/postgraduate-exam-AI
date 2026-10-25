function nextComboCount(isCorrect, currentCombo) {
  if (isCorrect === true) return currentCombo + 1
  if (isCorrect === false) return 0
  return currentCombo
}

function feedbackPatch(feedback) {
  return {
    feedbackVisible: true,
    feedbackType: feedback.type,
    feedbackTitle: feedback.title,
    feedbackDetail: feedback.detail,
    feedbackComboText: feedback.comboText,
    feedbackComboLevel: feedback.comboLevel,
    feedbackStarCount: feedback.starCount,
  }
}

module.exports = {
  nextComboCount,
  feedbackPatch,
}

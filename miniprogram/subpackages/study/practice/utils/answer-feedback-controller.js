const adapter = require('../../utils/question-runner-adapter')
const {
  nextComboCount,
  feedbackPatch,
} = require('./answer-feedback-state')

function createAnswerFeedbackController(options) {
  return {
    show(q, answer) {
      showImpl(options, q, answer)
    },
  }
}

function showImpl(options, q, answer) {
  const isCorrect = adapter.isAnswerCorrect(q, answer)
  const hasAnswer = !!answer
  const currentCombo = options.getComboCount()
  const nextCombo = nextComboCount(isCorrect, currentCombo)

  if (!hasAnswer) {
    options.setComboCount(nextCombo)
    options.setData({ feedbackVisible: false })
    return
  }

  if (isCorrect !== true && isCorrect !== false) {
    options.setComboCount(nextCombo)
    return
  }

  const feedback = buildFeedback(isCorrect, nextCombo)

  options.clearFeedbackTimer()
  options.setComboCount(nextCombo)
  options.setData(feedbackPatch(feedback))

  options.setFeedbackTimer(() => {
    options.setData({ feedbackVisible: false })
    options.clearFeedbackTimer()
  }, feedback.comboText ? 2000 : 1200)
}

function buildFeedback(isCorrect, comboCount) {
  if (isCorrect !== true) {
    return {
      type: 'wrong',
      title: '继续加油',
      detail: '先记录选择，交卷后集中复盘',
      comboText: '',
      comboLevel: '',
      starCount: 0,
    }
  }

  if (comboCount >= 10) {
    return {
      type: 'correct',
      title: '学霸连击',
      detail: '状态火热，无人能挡',
      comboText: `🔥 ${comboCount} 连对`,
      comboLevel: 'fire',
      starCount: 6,
    }
  }
  if (comboCount >= 5) {
    return {
      type: 'correct',
      title: '五连斩',
      detail: '进入心流状态，继续推进',
      comboText: `⚡ ${comboCount} 连对`,
      comboLevel: 'hot',
      starCount: 5,
    }
  }
  if (comboCount >= 3) {
    return {
      type: 'correct',
      title: '三连对',
      detail: '手感正热，保持这个状态',
      comboText: `${comboCount} 连对`,
      comboLevel: 'warm',
      starCount: 3,
    }
  }
  return {
    type: 'correct',
    title: '回答正确',
    detail: '这题很稳，保持当前节奏',
    comboText: '',
    comboLevel: '',
    starCount: 0,
  }
}

module.exports = {
  createAnswerFeedbackController,
}

function modeLabel(mode) {
  var map = { random: '随机挑战', sequential: '顺序推进', smart: '智能推荐' }
  return map[mode] || mode || ''
}

function createComputedFieldsController(options) {
  return {
    modeLabel,

    update(extras) {
      var data = {}
      data.selectedModeLabel = modeLabel(options.getSelectedMode())
      var count = Number(options.getCount() || 5)
      var minutesMap = { 5: 10, 10: 20, 20: 40 }
      data.countDisplay = count < 10 ? ('0' + count) : String(count)
      data.estimatedMinutes = minutesMap[count] || Math.max(5, count * 2)
      var total = options.getTotalQuestions() || 0
      var answered = options.getAnsweredCount() || 0
      data.progressPercent = total > 0 ? Math.round(answered / total * 100) : 0
      if (extras) Object.assign(data, extras)
      options.setData(data)
    },
  }
}

module.exports = {
  createComputedFieldsController,
  modeLabel,
}

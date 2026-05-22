Page({
  data: {
    correct: 0,
    wrong: 0,
    total: 0,
    passRate: 0,
    subject: '',
    recordId: 0,
    duration: 0,
  },

  onLoad(options) {
    const correct = parseInt(options.correct, 10) || 0
    const wrong = parseInt(options.wrong, 10) || 0
    const total = parseInt(options.total, 10) || 0
    const duration = parseInt(options.duration, 10) || 0

    this.setData({
      correct,
      wrong,
      total,
      duration,
      durationText: this._fmt(duration),
      passRate: total > 0 ? Math.round(correct / total * 100) : 0,
      subject: options.subject || '',
      recordId: parseInt(options.record_id, 10) || 0,
    })
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${m} 分 ${ss} 秒`
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || ''
  },

  goWrongBook() {
    wx.redirectTo({ url: '/pages/wrong-book/wrong-book' })
  },

  practiceAgain() {
    wx.redirectTo({ url: '/pages/practice/practice' })
  },

  goHome() {
    wx.redirectTo({ url: '/pages/home/home' })
  },
})

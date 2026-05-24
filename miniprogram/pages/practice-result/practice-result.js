Page({
  data: {
    correct: 0,
    wrong: 0,
    total: 0,
    passRate: 0,
    subject: '',
    duration: 0,
    durationText: '',
    results: [],
    showDetail: false,
  },

  onLoad(options) {
    const correct = parseInt(options.correct, 10) || 0
    const wrong = parseInt(options.wrong, 10) || 0
    const total = parseInt(options.total, 10) || 0
    const duration = parseInt(options.duration, 10) || 0

    // 从 storage 读取详细结果
    let results = []
    try {
      const stored = wx.getStorageSync('lastPracticeResult')
      if (stored && stored.results) {
        results = stored.results.map(r => ({
          ...r,
          _label: r.is_correct ? '✓' : '✗',
          _cls: r.is_correct ? 'correct' : 'wrong',
        }))
      }
    } catch (_) {}

    this.setData({
      correct,
      wrong,
      total,
      duration,
      durationText: this._fmt(duration),
      passRate: total > 0 ? Math.round(correct / total * 100) : 0,
      subject: options.subject || '',
      results,
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

  toggleDetail() {
    this.setData({ showDetail: !this.data.showDetail })
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

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
    showCelebration: false,
    celebrationIcon: '✓',
    celebrationTitle: '',
    celebrationDetail: '',
    celebrationMotto: '',
    subjectDisplay: '练习',
  },

  onLoad(options) {
    const correct = parseInt(options.correct, 10) || 0
    const wrong = parseInt(options.wrong, 10) || 0
    const total = parseInt(options.total, 10) || 0
    const duration = parseInt(options.duration, 10) || 0
    const passRate = total > 0 ? Math.round(correct / total * 100) : 0

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
      passRate,
      subject: options.subject || '',
      subjectDisplay: this.subjectLabel(options.subject || '') || '练习',
      results,
      ...this._celebrationCopy(passRate, correct, total),
    })
    this._showCelebration()
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${m} 分 ${ss} 秒`
  },

  _celebrationCopy(passRate, correct, total) {
    if (passRate >= 80) {
      return {
        celebrationIcon: '✓',
        celebrationTitle: '高质量挑战完成',
        celebrationDetail: `答对 ${correct}/${total} 题 · 正确率 ${passRate}%`,
        celebrationMotto: '这组表现很稳，继续把优势变成习惯',
      }
    }
    if (passRate >= 50) {
      return {
        celebrationIcon: '↗',
        celebrationTitle: '完成一次有效练习',
        celebrationDetail: `答对 ${correct}/${total} 题 · 正确率 ${passRate}%`,
        celebrationMotto: '复盘后再来一组，薄弱点会越来越少',
      }
    }
    return {
      celebrationIcon: '!',
      celebrationTitle: '薄弱点已暴露',
      celebrationDetail: `答对 ${correct}/${total} 题 · 正确率 ${passRate}%`,
      celebrationMotto: '先把错题吃透，这次练习就很有价值',
    }
  },

  _showCelebration() {
    if (this._celebrationTimer) clearTimeout(this._celebrationTimer)
    this.setData({ showCelebration: true })
    this._celebrationTimer = setTimeout(() => {
      this.setData({ showCelebration: false })
      this._celebrationTimer = null
    }, 2600)
  },

  dismissCelebration() {
    if (this._celebrationTimer) {
      clearTimeout(this._celebrationTimer)
      this._celebrationTimer = null
    }
    this.setData({ showCelebration: false })
  },

  onUnload() {
    if (this._celebrationTimer) {
      clearTimeout(this._celebrationTimer)
      this._celebrationTimer = null
    }
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

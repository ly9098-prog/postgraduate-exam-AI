const { formatInlineMathText } = require('../../utils/math-format')
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
    celebrationRewardText: '',
    celebrationType: 'steady',
    growthTitle: '',
    growthDesc: '',
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
          correct_answer: formatInlineMathText(r.correct_answer),
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
      ...this._celebrationCopy(passRate, correct, wrong, total),
    })
    this._showCelebration()
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${m} 分 ${ss} 秒`
  },

  _celebrationCopy(passRate, correct, wrong, total) {
    if (passRate >= 80) {
      return {
        celebrationIcon: '✓',
        celebrationTitle: '高质量挑战完成',
        celebrationDetail: `答对 ${correct}/${total} 题 · 正确率 ${passRate}%`,
        celebrationMotto: '这组表现很稳，继续把优势变成习惯',
        celebrationRewardText: `专注星光 +${Math.max(1, correct)}`,
        celebrationType: 'excellent',
        growthTitle: `练习经验 +${Math.max(1, total)}`,
        growthDesc: '高正确率完成挑战，今日成长能量已点亮',
      }
    }
    if (passRate >= 50) {
      return {
        celebrationIcon: '↗',
        celebrationTitle: '完成一次有效练习',
        celebrationDetail: `答对 ${correct}/${total} 题 · 正确率 ${passRate}%`,
        celebrationMotto: '复盘后再来一组，薄弱点会越来越少',
        celebrationRewardText: `复盘能量 +${Math.max(1, correct)}`,
        celebrationType: 'steady',
        growthTitle: `练习经验 +${Math.max(1, total)}`,
        growthDesc: '本组薄弱点已记录，继续巩固会更稳',
      }
    }
    return {
      celebrationIcon: '!',
      celebrationTitle: '薄弱点已暴露',
      celebrationDetail: `答对 ${correct}/${total} 题 · 正确率 ${passRate}%`,
      celebrationMotto: '先把错题吃透，这次练习就很有价值',
      celebrationRewardText: '错题诊断 +1',
      celebrationType: 'focus',
      growthTitle: `复盘经验 +${Math.max(1, wrong || total)}`,
      growthDesc: '错题已进入复盘路径，下一组会更有方向',
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

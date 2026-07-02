const api = require('../../utils/api')
const { formatInlineMathText } = require('../../utils/math-format')
Page({
  data: {
    correct: 0,
    wrong: 0,
    skipped: 0,
    total: 0,
    answeredCount: 0,
    passRate: 0,
    subject: '',
    duration: 0,
    durationText: '',
    results: [],
    showDetail: false,
    showCelebration: false,
    celebrationTitle: '',
    celebrationDetail: '',
    celebrationMotto: '',
    celebrationRewardText: '',
    celebrationType: 'steady',
    growthTitle: '',
    growthDesc: '',
    growthLevel: '',
    growthExpText: '',
    growthLevelPct: 0,
    growthBadgeCount: 0,
    subjectDisplay: '练习',
  },

  async onLoad(options) {
    const correct = parseInt(options.correct, 10) || 0
    const wrong = parseInt(options.wrong, 10) || 0
    const total = parseInt(options.total, 10) || 0
    const duration = parseInt(options.duration, 10) || 0
    const passRate = total > 0 ? Math.round(correct / total * 100) : 0
    const answeredCount = correct + wrong

    // 从 storage 读取详细结果
    let results = []
    let stored = null
    try {
      stored = wx.getStorageSync('lastPracticeResult')
      if (stored && stored.results) {
        const questions = stored.questions || []
        const questionById = {}
        questions.forEach(function(q) { if (q && q.id) questionById[String(q.id)] = q })
        results = stored.results.map(function(r) {
          const q = questionById[String(r.question_id)] || {}
          const stemText = (q.content && (q.content.stem || q.content.text || q.content.title || q.content.question)) || q.stem || q.title || q.question || q.text || ''
          return {
            ...r,
            correct_answer: formatInlineMathText(r.correct_answer),
            _label: r.is_correct ? '✓' : '✗',
            _cls: r.is_correct ? 'correct' : 'wrong',
            _stemPreview: stemText ? (stemText.length > 50 ? stemText.slice(0, 50) + '...' : stemText) : '',
            _userAnswer: r.user_answer || '',
          }
        })
      }
    } catch (_) {}

    const skipped = (stored && stored.skipped) || 0
    this.setData({
      correct,
      wrong,
      skipped,
      total,
      answeredCount,
      duration,
      durationText: this._fmt(duration),
      passRate,
      subject: options.subject_id || '',
      subjectDisplay: decodeURIComponent(options.subject_name || '') || '练习',
      results,
      ...this._celebrationCopy(passRate, correct, wrong, total, answeredCount),
    })
    this._showCelebration()
    this._loadGrowth()
  },

  async _loadGrowth() {
    try {
      const growth = await api.get('/stats/growth')
      if (!growth) return
      const unlockedBadges = (growth.badges || []).filter(b => b.unlocked).length
      this.setData({
        growthLevel: growth.level_title || 'Lv1 起步',
        growthExpText: `${growth.exp_current || 0} / ${growth.exp_to_next || 0} EXP`,
        growthLevelPct: growth.level_progress_pct || 0,
        growthBadgeCount: unlockedBadges,
        growthTitle: `练习经验 +${Math.max(1, this.data.total)}`,
        growthDesc: unlockedBadges > 0
          ? `已点亮 ${unlockedBadges} 个徽章 · ${growth.level_title || ''}`
          : `当前 ${growth.level_title || 'Lv1 起步'} · 继续保持`,
      })
    } catch (_) {}
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    const m = Math.floor(s / 60)
    const ss = s % 60
    return `${m} 分 ${ss} 秒`
  },

  _celebrationCopy(passRate, correct, wrong, total, answeredCount) {
    answeredCount = answeredCount || (correct + wrong)
    const completedPct = total > 0 ? Math.round(answeredCount / total * 100) : 0
    const answeredAccuracy = answeredCount > 0 ? Math.round(correct / answeredCount * 100) : 0
    const detailLines = [`答对 ${correct}/${total} 题`]
    if (answeredCount < total) {
      detailLines.push(`完成率 ${completedPct}%`)
    }
    detailLines.push(answeredCount > 0 ? `已答正确率 ${answeredAccuracy}%` : `正确率 ${passRate}%`)
    const celebrationDetail = detailLines.join(' · ')
    if (passRate >= 80) {
      return {
        celebrationTitle: '高质量挑战完成',
        celebrationDetail,
        celebrationMotto: '这组表现很稳，继续把优势变成习惯',
        celebrationRewardText: `专注星光 +${Math.max(1, correct)}`,
        celebrationType: 'practice',
        growthTitle: `练习经验 +${Math.max(1, total)}`,
        growthDesc: '高正确率完成挑战，今日成长能量已点亮',
      }
    }
    if (passRate >= 50) {
      return {
        celebrationTitle: '完成一次有效练习',
        celebrationDetail,
        celebrationMotto: '复盘后再来一组，薄弱点会越来越少',
        celebrationRewardText: `复盘能量 +${Math.max(1, correct)}`,
        celebrationType: 'practice',
        growthTitle: `练习经验 +${Math.max(1, total)}`,
        growthDesc: '本组薄弱点已记录，继续巩固会更稳',
      }
    }
    return {
      celebrationTitle: '薄弱点已暴露',
      celebrationDetail,
      celebrationMotto: '先把错题吃透，这次练习就很有价值',
      celebrationRewardText: '错题诊断 +1',
      celebrationType: 'practice',
      growthTitle: `复盘经验 +${Math.max(1, wrong || total)}`,
      growthDesc: '错题已进入复盘路径，下一组会更有方向',
    }
  },

  _showCelebration() {
    this._clearCelebrationTimer()
    this.setData({ showCelebration: true })
    this._celebrationTimer = setTimeout(() => {
      this.setData({ showCelebration: false })
      this._celebrationTimer = null
    }, 2600)
  },

  dismissCelebration() {
    this._clearCelebrationTimer()
    this.setData({ showCelebration: false })
  },

  onHide() {
    this._clearCelebrationTimer()
    if (this.data.showCelebration) this.setData({ showCelebration: false })
  },

  onUnload() {
    this._clearCelebrationTimer()
  },

  _clearCelebrationTimer() {
    if (this._celebrationTimer) {
      clearTimeout(this._celebrationTimer)
      this._celebrationTimer = null
    }
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

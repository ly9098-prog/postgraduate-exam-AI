const api = require('../../../utils/api')

function minutes(sec) {
  const value = Number(sec || 0)
  return value > 0 ? Math.max(1, Math.round(value / 60)) : 0
}

function typeLabel(type) {
  return type === 'past_exam_choice' ? '真题选择题' : '选择题模拟卷'
}

Page({
  data: {
    loading: true,
    errorText: '',
    papers: [],
    startingId: 0,
    suggestedPaperId: 0,
  },

  onLoad(options = {}) {
    const suggestedPaperId = Number(options.suggested_paper_id) || 0
    this.setData({ suggestedPaperId })
    this.loadPapers()
  },

  onShow() {
    if (this._loadedOnce) this.loadPapers({ silent: true })
  },

  async loadPapers(options = {}) {
    if (!options.silent) this.setData({ loading: true, errorText: '' })
    try {
      const rows = await api.get('/exams/papers')
      const papers = (Array.isArray(rows) ? rows : []).map((item) => ({
        ...item,
        typeLabel: typeLabel(item.paper_type),
        durationMinutes: minutes(item.duration_sec),
        scoreText: Number(item.total_choice_score || 0).toFixed(0),
        bestScoreText: item.best_choice_score == null ? '' : Number(item.best_choice_score).toFixed(1),
        canResume: item.latest_attempt_status === 'in_progress' && !!item.latest_attempt_id,
        isSuggested: Number(item.id) === Number(this.data.suggestedPaperId),
      }))
      this._loadedOnce = true
      this.setData({ papers, loading: false, errorText: '' })
    } catch (error) {
      this.setData({ loading: false, errorText: api.getErrorMessage(error) })
    }
  },

  async openPaper(e) {
    const id = Number(e.currentTarget.dataset.id)
    const paper = this.data.papers.find((item) => Number(item.id) === id)
    if (!paper || this.data.startingId) return
    if (paper.canResume) {
      wx.navigateTo({ url: `/subpackages/exam/exam-runner/index?attempt_id=${paper.latest_attempt_id}` })
      return
    }

    const detail = await new Promise((resolve) => {
      wx.showModal({
        title: paper.typeLabel,
        content: `${paper.title}\n\n本功能仅覆盖 408 选择题部分，共 ${paper.question_count} 题、${paper.scoreText} 分。${paper.durationMinutes ? `限时 ${paper.durationMinutes} 分钟。` : ''}\n\n选择题得分不会被表述为完整 408 总成绩。`,
        confirmText: '开始作答',
        cancelText: '稍后再做',
        success: resolve,
        fail: () => resolve({ confirm: false }),
      })
    })
    if (!detail.confirm) return

    this.setData({ startingId: id })
    try {
      const attempt = await api.post(`/exams/papers/${id}/attempts`, {
        request_id: api.createRequestId(),
      })
      wx.navigateTo({ url: `/subpackages/exam/exam-runner/index?attempt_id=${attempt.id}` })
    } catch (error) {
      wx.showToast({ title: api.getErrorMessage(error), icon: 'none' })
    } finally {
      this.setData({ startingId: 0 })
    }
  },

  goHistory() {
    wx.navigateTo({ url: '/subpackages/exam/history/index' })
  },

  goBack() {
    wx.navigateBack({ delta: 1 })
  },
})

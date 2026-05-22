const api = require('../../utils/api')

Page({
  data: {
    wq: null,
    optionKeys: [],
    aiResult: null,
    aiLoading: false,
    aiFallback: false,
    loading: true,
    // SM-2 评分
    showRating: false,
    rating: -1,
    submittingRating: false,
    rated: false,
    nextReviewDate: '',
  },

  onLoad(options) {
    this.loadData(options.id)
  },

  async loadData(wqId) {
    this.setData({ loading: true })
    try {
      const wq = await api.get(`/wrong-questions/${wqId}`)
      if (!wq) throw new Error('not found')

      const optionKeys = wq.options ? Object.keys(wq.options) : []
      this.setData({ wq, optionKeys, loading: false, showRating: !wq.mastered })
      this.loadAiAnalysis(wqId)
    } catch (e) {
      console.error('加载错题详情失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false })
    }
  },

  async loadAiAnalysis(wqId) {
    this.setData({ aiLoading: true })
    try {
      const result = await api.post('/ai/error-analysis', { wrong_question_id: wqId })
      this.setData({
        aiResult: result.content,
        aiFallback: result.from_fallback,
        aiLoading: false,
      })
    } catch (e) {
      console.error('加载 AI 分析失败', e)
      this.setData({ aiLoading: false, aiFallback: true })
    }
  },

  async markMastered() {
    try {
      await api.put(`/wrong-questions/${this.data.wq.id}`, { mastered: true })
      wx.showToast({ title: '已标记掌握', icon: 'success' })
      this.setData({ 'wq.mastered': true, showRating: false, rated: true })
    } catch (e) {
      console.error('标记掌握失败', e)
      wx.showToast({ title: '操作失败', icon: 'none' })
    }
  },

  // --- SM-2 质量评分 ---
  selectRating(e) {
    if (this.data.submittingRating || this.data.rated) return
    this.setData({ rating: e.currentTarget.dataset.value })
  },

  async submitRating() {
    if (this.data.rating < 0) return
    this.setData({ submittingRating: true })
    try {
      const res = await api.put(`/wrong-questions/${this.data.wq.id}/quality`, {
        quality: this.data.rating,
      })
      const next = res.next_review_date || ''
      const dateStr = next ? next.slice(0, 10) : ''
      wx.showToast({ title: `评分完成，下次复习: ${dateStr || '已掌握'}`, icon: 'none' })
      this.setData({
        rated: true,
        submittingRating: false,
        nextReviewDate: dateStr,
        'wq.efactor': res.efactor,
        'wq.interval': res.interval,
        'wq.repetitions': res.repetitions,
        'wq.next_review_date': res.next_review_date,
        'wq.mastered': res.mastered,
      })
      if (res.mastered) {
        this.setData({ showRating: false })
      }
    } catch (e) {
      console.error('评分提交失败', e)
      wx.showToast({ title: '评分失败', icon: 'none' })
      this.setData({ submittingRating: false })
    }
  },

  ratingLabel(v) {
    const labels = ['完全忘记', '很困难', '有印象', '较困难答对', '稍有犹豫', '完全正确']
    return labels[v] || ''
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s
  },

  errorTypeLabel(t) {
    const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
    return map[t] || t
  },
})

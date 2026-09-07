const api = require('../../../utils/api')

const STATUS_TEXT = { no_data: '未开始', insufficient: '数据不足', weak: '薄弱', developing: '提升中', good: '良好', mastered: '已掌握' }

Page({
  data: { loading: true, error: '', detail: null, syllabusVersion: null, recent: [], statusText: '' },

  onLoad(options) {
    this.knowledgePointId = Number(options && options.knowledge_point_id)
    if (!this.knowledgePointId) {
      this.setData({ loading: false, error: '知识点参数无效' })
      return
    }
    this.loadDetail()
  },

  onShow() {
    if (this._loadedOnce) this.loadDetail(false)
  },

  async loadDetail(showLoading = true) {
    if (showLoading) this.setData({ loading: true, error: '' })
    try {
      const detail = await api.get(`/knowledge-map/points/${this.knowledgePointId}`)
      const recent = (Array.isArray(detail.recent_answers) ? detail.recent_answers : []).map(item => ({ ...item, mark: item.is_correct ? '✓' : '×', cls: item.is_correct ? 'correct' : 'wrong' }))
      wx.setNavigationBarTitle({ title: detail.name || '知识点详情' })
      this._loadedOnce = true
      this.setData({
        loading: false,
        error: '',
        detail,
        syllabusVersion: detail.syllabus_version || null,
        recent,
        statusText: STATUS_TEXT[detail.status] || '未开始',
        scoreText: detail.mastery_score == null ? '--' : `${Math.round(Number(detail.mastery_score) || 0)}%`,
        confidenceText: `${Math.round((Number(detail.confidence) || 0) * 100)}%`,
        accuracyText: detail.accuracy == null ? '--' : `${Math.round(Number(detail.accuracy) * 100)}%`,
      })
    } catch (error) {
      if (showLoading) this.setData({ loading: false, error: api.getErrorMessage(error) })
    }
  },

  startPractice() {
    const d = this.data.detail
    const p = d && d.practice_route_params
    if (!p || !p.subject_id || !p.knowledge_point_id) {
      wx.showToast({ title: '当前知识点暂无可练题目', icon: 'none' })
      return
    }
    wx.navigateTo({
      url: `/subpackages/study/practice/practice?subject_id=${p.subject_id}&mode=random&count=${p.count || 10}&knowledge_point_id=${p.knowledge_point_id}&allow_repeat=1&autostart=1&source=knowledge_map`,
    })
  },

  openRelation(event) {
    const id = Number(event.currentTarget.dataset.id)
    if (!id || id === this.knowledgePointId) return
    wx.redirectTo({ url: `/subpackages/study/knowledge-detail/index?knowledge_point_id=${id}` })
  },

  retry() { this.loadDetail() },
})

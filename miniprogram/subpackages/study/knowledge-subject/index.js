const api = require('../../../utils/api')

const STATUS_TEXT = {
  no_data: '未开始', insufficient: '数据不足', weak: '薄弱', developing: '提升中', good: '良好', mastered: '已掌握',
}

Page({
  data: { loading: true, error: '', subject: null, nodes: [], visibleNodes: [], filter: 'all' },

  onLoad(options) {
    this.subjectId = Number(options && options.subject_id)
    if (!this.subjectId) {
      this.setData({ loading: false, error: '科目参数无效' })
      return
    }
    this.loadMap()
  },

  onPullDownRefresh() { this.loadMap().finally(() => wx.stopPullDownRefresh()) },

  async loadMap() {
    this.setData({ loading: true, error: '' })
    try {
      const data = await api.get(`/knowledge-map/subjects/${this.subjectId}`)
      const nodes = (Array.isArray(data.nodes) ? data.nodes : []).map((item) => {
        const score = item.mastery_score == null ? null : Math.round(Number(item.mastery_score) || 0)
        return {
          ...item,
          scoreText: score == null ? '--' : `${score}%`,
          statusText: STATUS_TEXT[item.status] || '未开始',
          statusClass: `status-${item.status || 'no_data'}`,
          indent: Math.min(4, Number(item.depth) || 0) * 30,
          accuracyText: item.accuracy == null ? '--' : `${Math.round(Number(item.accuracy) * 100)}%`,
          hasPractice: Number(item.trainable_question_count) > 0,
        }
      })
      wx.setNavigationBarTitle({ title: `${data.subject.subject_name} · 知识树` })
      this.setData({ loading: false, subject: data.subject, nodes }, () => this.applyFilter())
    } catch (error) {
      this.setData({ loading: false, error: api.getErrorMessage(error) })
    }
  },

  setFilter(event) {
    const filter = String(event.currentTarget.dataset.filter || 'all')
    this.setData({ filter }, () => this.applyFilter())
  },

  applyFilter() {
    const filter = this.data.filter
    let items = this.data.nodes
    if (filter === 'weak') items = items.filter(item => item.status === 'weak' || item.status === 'developing')
    if (filter === 'unseen') items = items.filter(item => item.status === 'no_data' || item.status === 'insufficient')
    if (filter === 'mastered') items = items.filter(item => item.status === 'good' || item.status === 'mastered')
    this.setData({ visibleNodes: items })
  },

  openPoint(event) {
    const id = Number(event.currentTarget.dataset.id)
    if (!id) return
    wx.navigateTo({ url: `/subpackages/study/knowledge-detail/index?knowledge_point_id=${id}` })
  },

  practicePoint(event) {
    const item = (this.data.nodes || []).find(node => Number(node.knowledge_point_id) === Number(event.currentTarget.dataset.id))
    if (!item || !item.hasPractice) return
    const count = Math.min(10, Math.max(1, Number(item.trainable_question_count) || 1))
    wx.navigateTo({
      url: `/subpackages/study/practice/practice?subject_id=${this.subjectId}&mode=random&count=${count}&knowledge_point=${encodeURIComponent(item.name)}&allow_repeat=1&autostart=1&source=knowledge_map`,
    })
  },

  retry() { this.loadMap() },
})

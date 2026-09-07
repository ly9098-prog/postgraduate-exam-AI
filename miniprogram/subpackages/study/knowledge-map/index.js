const api = require('../../../utils/api')

const STATUS_META = {
  no_data: { text: '未开始', hint: '完成相关练习后生成掌握度' },
  insufficient: { text: '数据不足', hint: '继续练习，达到可靠样本后展示' },
  weak: { text: '薄弱', hint: '建议优先专项强化' },
  developing: { text: '提升中', hint: '掌握度正在建立' },
  good: { text: '良好', hint: '保持复习与巩固' },
  mastered: { text: '已掌握', hint: '注意周期复习防止遗忘' },
}

Page({
  data: {
    loading: true,
    error: '',
    scopeReady: true,
    subjects: [],
    observedTotal: 0,
    weakTotal: 0,
  },

  onLoad() {
    this.loadOverview()
  },

  onPullDownRefresh() {
    this.loadOverview().finally(() => wx.stopPullDownRefresh())
  },

  async loadOverview() {
    this.setData({ loading: true, error: '' })
    try {
      const data = await api.get('/knowledge-map/overview')
      const subjects = (Array.isArray(data.subjects) ? data.subjects : []).map((item) => {
        const meta = STATUS_META[item.status] || STATUS_META.no_data
        const score = item.mastery_score == null ? null : Math.max(0, Math.min(100, Math.round(Number(item.mastery_score) || 0)))
        const coverage = Math.max(0, Math.min(100, Math.round((Number(item.coverage_ratio) || 0) * 100)))
        return {
          ...item,
          score,
          scoreText: score == null ? '--' : `${score}%`,
          barWidth: score == null ? 0 : score,
          coverage,
          statusText: meta.text,
          statusHint: meta.hint,
          statusClass: `status-${item.status || 'no_data'}`,
          progressText: `${Number(item.reliable_knowledge_points) || 0}/${Number(item.trainable_knowledge_points) || 0} 个知识点数据可靠`,
        }
      })
      this.setData({
        loading: false,
        scopeReady: data.scope_ready !== false,
        subjects,
        observedTotal: subjects.reduce((sum, item) => sum + (Number(item.observed_knowledge_points) || 0), 0),
        weakTotal: subjects.reduce((sum, item) => sum + (Number(item.weak_knowledge_points) || 0), 0),
      })
    } catch (error) {
      this.setData({ loading: false, error: api.getErrorMessage(error) })
    }
  },

  openSubject(event) {
    const subjectId = Number(event.currentTarget.dataset.subjectId)
    if (!subjectId) return
    wx.navigateTo({ url: `/subpackages/study/knowledge-subject/index?subject_id=${subjectId}` })
  },

  retry() {
    this.loadOverview()
  },
})

const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    overview: null,
    subjects: [],
    trends: [],
    behavior: null,
    forgetting: null,
  },

  onShow() {
    this.loadData()
  },

  async loadData() {
    this.setData({ loading: true })
    try {
      const res = await api.get('/stats/dashboard')
      this.setData(this._process(res))
    } catch (e) {
      console.error('加载学习统计失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false, overview: null, subjects: [], trends: [], behavior: null, forgetting: null })
    }
  },

  _process(res) {
    const overview = res.overview || {}
    const subjects = (res.subject_stats || []).filter(s => s.total_questions > 0)
    const trends = res.recent_trend || []
    const behavior = res.behavior || {}
    const forgetting = res.forgetting || {}

    // 预计算总览字段
    const ov = {
      ...overview,
      _accuracyText: (overview.accuracy * 100 || 0).toFixed(1) + '%',
      _totalDuration: this._fmt(overview.total_duration_sec || 0),
      _todayDuration: this._fmt(overview.today_duration_sec || 0),
    }

    // 预计算学科字段
    const subs = subjects.map(s => ({
      ...s,
      _accPct: (s.accuracy * 100 || 0).toFixed(0),
      _accClass: s.accuracy >= 0.7 ? 'green' : s.accuracy >= 0.4 ? 'orange' : 'red',
      _durationText: this._fmt(s.total_duration_sec || 0),
    }))

    // 预计算趋势字段
    const trs = trends.map(t => ({
      ...t,
      _shortDate: (t.date || '').slice(5),
      _barH: Math.max(8, Math.min(120, ((t.questions || 0) / 20) * 80 + 8)),
      _accPct: (t.accuracy * 100 || 0).toFixed(0),
      _accClass: t.accuracy >= 0.7 ? 'green' : t.accuracy >= 0.4 ? 'orange' : 'red',
    }))

    // 预计算行为字段
    const bh = {
      ...behavior,
      _viewRate: (behavior.view_answer_rate * 100 || 0).toFixed(0) + '%',
      _abandonRate: (behavior.abandon_rate * 100 || 0).toFixed(0) + '%',
    }

    return {
      overview: ov,
      subjects: subs,
      trends: trs,
      behavior: bh,
      forgetting,
      loading: false,
    }
  },

  _fmt(sec) {
    const s = Math.max(0, sec || 0)
    if (s < 60) return `${s}秒`
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}分${s % 60}秒`
    return `${Math.floor(m / 60)}时${m % 60}分`
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || ''
  },
})

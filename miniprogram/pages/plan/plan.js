const api = require('../../utils/api')

Page({
  data: {
    dueList: [],
    stats: {},
    loading: true,
  },

  onShow() {
    this.loadAll()
  },

  async loadAll() {
    this.setData({ loading: true })
    try {
      const [dueRes, statsRes] = await Promise.all([
        api.get('/review/due', { page: 1, page_size: 50 }),
        api.get('/review/stats'),
      ])
      const dueList = (dueRes.items || []).map(item => ({
        ...item,
        _subjectLabel: this.subjectLabel(item.subject),
        _intervalLabel: this.intervalLabel(item.interval),
      }))
      const reviewedToday = statsRes.reviewed_today || 0
      const dueToday = statsRes.due_today || 0
      const mastered = statsRes.mastered || 0
      const totalWrong = statsRes.total_wrong || 0
      const todayTotal = reviewedToday + dueToday
      const stats = {
        ...statsRes,
        _reviewProgressPct: todayTotal ? Math.max(6, Math.min(100, reviewedToday / todayTotal * 100)).toFixed(0) : 0,
        _masteredPct: totalWrong ? Math.max(6, Math.min(100, mastered / totalWrong * 100)).toFixed(0) : 0,
      }
      this.setData({
        dueList,
        stats,
        loading: false,
      })
    } catch (e) {
      console.error('加载复习数据失败', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false })
    }
  },

  goReview(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}` })
  },

  goPractice() {
    wx.navigateTo({ url: '/pages/practice/practice' })
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s
  },

  intervalLabel(days) {
    if (!days && days !== 0) return ''
    if (days === 0) return '首次复习'
    if (days === 1) return '明天'
    if (days <= 7) return `${days} 天后`
    return `${Math.round(days / 7)} 周后`
  },
})

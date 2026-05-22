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
      this.setData({
        dueList: dueRes.items || [],
        stats: statsRes,
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

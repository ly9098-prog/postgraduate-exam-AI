const api = require('../../utils/api')
const auth = require('../../utils/auth')

Page({
  data: {
    user: {},
    wrongStats: {},
    practiceCount: 0,
    maxCount: 0,
    greeting: '你好',
    dateStr: '',
    authed: false,
  },

  onShow() {
    const user = auth.getUser() || {}
    const authed = auth.isLoggedIn()
    this.setData({ user, authed, greeting: this.getGreeting(), dateStr: this.getDateStr() })
    if (!authed) return
    this.loadStats()
    this.loadPracticeCount()
  },

  getGreeting() {
    const h = new Date().getHours()
    if (h < 6) return '夜深了'
    if (h < 9) return '早上好'
    if (h < 12) return '上午好'
    if (h < 14) return '中午好'
    if (h < 18) return '下午好'
    return '晚上好'
  },

  getDateStr() {
    const d = new Date()
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.getMonth()+1}月${d.getDate()}日 星期${week[d.getDay()]}`
  },

  async loadStats() {
    try {
      const stats = await api.get('/wrong-questions/stats')
      const maxCount = (stats.by_subject || []).reduce((max, s) => Math.max(max, s.count), 1)
      this.setData({ wrongStats: stats, maxCount })
    } catch (e) {
      console.error('加载错题统计失败', e)
    }
  },

  async loadPracticeCount() {
    try {
      const data = await api.get('/practice/records', { page: 1, page_size: 1 })
      this.setData({ practiceCount: data.total })
    } catch (e) {
      console.error('加载练习记录失败', e)
    }
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s
  },

  startRandom() { wx.navigateTo({ url: '/pages/practice/practice' }) },
  goWrongBook() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book' }) },
  goReview() { wx.navigateTo({ url: '/pages/plan/plan' }) },
  goAnalysis() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book?tab=analysis' }) },
  goDashboard() { wx.navigateTo({ url: '/pages/dashboard/dashboard' }) },
  goImport() { wx.navigateTo({ url: '/pages/import/import' }) },
})

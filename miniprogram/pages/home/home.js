const api = require('../../utils/api')
const auth = require('../../utils/auth')

Page({
  data: {
    user: {},
    wrongStats: {},
    greeting: '你好',
    dateStr: '',
    authed: false,
    isAdmin: false,
  },

  async onShow() {
    const authed = auth.isLoggedIn()
    this.setData({ user: auth.getUser() || {}, authed, isAdmin: auth.isAdmin(), greeting: this.getGreeting(), dateStr: this.getDateStr() })
    if (!authed) return
    try {
      const syncedUser = await auth.syncCurrentUser()
      this.setData({ user: syncedUser || {}, isAdmin: auth.isAdmin() })
    } catch (e) {
      console.error('同步用户权限失败', e)
    }
    this.loadStats()
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
      this.setData({ wrongStats: stats })
    } catch (e) {
      console.error('加载错题统计失败', e)
    }
  },

  startRandom() { wx.navigateTo({ url: '/pages/practice/practice' }) },
  goWrongBook() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book' }) },
  goReview() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book?tab=due' }) },
  goDashboard() { wx.navigateTo({ url: '/pages/dashboard/dashboard' }) },
  goImport() {
    wx.navigateTo({ url: '/pages/import/import' })
  },
})

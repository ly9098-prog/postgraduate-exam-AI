const auth = require('../../utils/auth')

Page({
  data: {
    user: {},
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

  startRandom() { wx.navigateTo({ url: '/pages/practice/practice' }) },
  goWrongBook() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book' }) },
  goReview() { wx.navigateTo({ url: '/pages/review-today/review-today' }) },
  goDashboard() { wx.navigateTo({ url: '/pages/dashboard/dashboard' }) },
  goPomodoro() { wx.navigateTo({ url: '/pages/pomodoro/pomodoro' }) },
  goImport() {
    wx.navigateTo({ url: '/pages/import/import' })
  },
})

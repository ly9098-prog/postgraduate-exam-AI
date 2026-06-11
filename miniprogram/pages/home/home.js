const auth = require('../../utils/auth')

Page({
  data: {
    user: {},
    greeting: '',
    dateStr: '',
    motto: '',
    authed: false,
    isAdmin: false,
  },

  async onShow() {
    const authed = auth.isLoggedIn()
    this.setData({
      user: auth.getUser() || {},
      authed,
      isAdmin: auth.isAdmin(),
      greeting: this.getGreeting(),
      dateStr: this.getDateStr(),
      motto: this.getMotto(),
    })
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

  getMotto() {
    const h = new Date().getHours()
    if (h < 6) return '休息也是学习的一部分，明天再战'
    if (h < 9) return '清晨是记忆的黄金时间'
    if (h < 12) return '开始今天的学习计划吧'
    if (h < 14) return '午后小憩一下，学习更高效'
    if (h < 18) return '保持专注，坚持就是胜利'
    return '完成今日计划，收获满满成就感'
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

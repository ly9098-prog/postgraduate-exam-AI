const api = require('../../utils/api')
const auth = require('../../utils/auth')

Page({
  data: {
    user: {},
    wrongStats: {},
    practiceCount: 0,
    maxCount: 0,
    subjectPieData: [],
    pieTotal: 0,
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
      const bySubject = stats.by_subject || []
      const maxCount = bySubject.reduce((max, s) => Math.max(max, s.count), 1)
      const subjectPieData = this.buildSubjectPieData(bySubject)
      const pieTotal = subjectPieData.reduce((total, s) => total + s.count, 0)
      this.setData({ wrongStats: stats, maxCount, subjectPieData, pieTotal }, () => {
        this.drawSubjectPie()
      })
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

  buildSubjectPieData(list) {
    const total = (list || []).reduce((sum, item) => sum + (item.count || 0), 0)
    const palette = ['#5B7B9A', '#C49A6B', '#6FA58B', '#D48B7D', '#7D8CC4', '#B58CC5']
    if (!total) return []
    let start = 0
    return (list || [])
      .filter(item => item && item.count > 0)
      .map((item, index) => {
        const percent = item.count / total
        const end = start + percent * 360
        const data = {
          ...item,
          _label: this.subjectLabel(item.subject),
          _percentText: (percent * 100).toFixed(1),
          _color: palette[index % palette.length],
          _startAngle: start,
          _endAngle: end,
        }
        start = end
        return data
      })
  },

  subjectLabel(s) {
    var map = {
      math2: '数学二', 'math2-calculus': '数学二·高数', 'math2-linalg': '数学二·线代',
      exam408: '408', 'exam408-ds': '408·DS', 'exam408-os': '408·OS',
      'exam408-co': '408·CO', 'exam408-cn': '408·CN',
      english: '英语',
    }
    return map[s] || s
  },

  drawSubjectPie() {
    if (!this.data.subjectPieData.length) return
    const query = wx.createSelectorQuery().in(this)
    query.select('#subject-pie-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const canvasSize = Math.min(rect.width, rect.height)
      const ctx = wx.createCanvasContext('subject-pie-canvas', this)
      const center = canvasSize / 2
      const radius = center - 10
      ctx.clearRect(0, 0, canvasSize, canvasSize)
      this.data.subjectPieData.forEach(item => {
        const start = (item._startAngle - 90) * Math.PI / 180
        const end = (item._endAngle - 90) * Math.PI / 180
        ctx.beginPath()
        ctx.moveTo(center, center)
        ctx.setFillStyle(item._color)
        ctx.arc(center, center, radius, start, end)
        ctx.closePath()
        ctx.fill()
      })
      ctx.draw()
    }).exec()
  },

  startRandom() { wx.navigateTo({ url: '/pages/practice/practice' }) },
  goWrongBook() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book' }) },
  goReview() { wx.navigateTo({ url: '/pages/plan/plan' }) },
  goAnalysis() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book?tab=analysis' }) },
  goDashboard() { wx.navigateTo({ url: '/pages/dashboard/dashboard' }) },
  goImport() {
    wx.navigateTo({ url: '/pages/import/import' })
  },
})

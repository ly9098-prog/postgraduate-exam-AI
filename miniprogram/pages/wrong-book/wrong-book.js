const api = require('../../utils/api')
const config = require('../../config')

Page({
  data: {
    tab: 'all',
    list: [],
    stats: {},
    reviewStats: {},
    page: 1,
    hasMore: false,
    loading: false,
    enableMathImage: false,
  },

  onLoad(options) {
    this.setData({ enableMathImage: config.enableMathImage || false })
    if (options.tab && ['all', 'due', 'mastered'].includes(options.tab)) {
      this.setData({ tab: options.tab })
    }
  },

  onShow() {
    this.setData({ list: [], page: 1 })
    this.loadStats()
    this.loadList(true)
  },

  async loadStats() {
    try {
      const [stats, reviewStats] = await Promise.all([
        api.get('/wrong-questions/stats'),
        api.get('/review/stats'),
      ])
      this.setData({ stats, reviewStats })
    } catch (e) {
      console.error('加载错题统计失败', e)
    }
  },

  async loadList(reset = false) {
    const page = reset ? 1 : this.data.page
    this.setData({ loading: true })

    try {
      let data
      if (this.data.tab === 'due') {
        data = await api.get('/review/due', { page, page_size: 20 })
      } else {
        const params = { page, page_size: 20 }
        if (this.data.tab === 'mastered') params.mastered = true
        data = await api.get('/wrong-questions', params)
      }

      const items = (data.items || []).map(item => ({
        ...item,
        _subjectLabel: this.subjectLabel(item.subject),
        _errorTypeLabel: this.errorTypeLabel(item.error_type),
        _intervalLabel: this.intervalLabel(item.interval),
      }))

      this.setData({
        list: reset ? items : [...this.data.list, ...items],
        hasMore: page < data.total_pages,
        page: reset ? 2 : page + 1,
        loading: false,
      })
    } catch (e) {
      console.error('加载错题列表失败', e)
      this.setData({ loading: false })
    }
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab
    if (tab === this.data.tab) return
    this.setData({ tab, list: [], page: 1 })
    this.loadList(true)
  },

  loadMore() {
    this.loadList()
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id
    if (this.data.tab === 'due') {
      wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}` })
    } else {
      const ids = this.data.list.map(item => item.id).join(',')
      wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}&ids=${ids}` })
    }
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

  errorTypeLabel(t) {
    const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
    return map[t] || t
  },

  intervalLabel(days) {
    if (!days && days !== 0) return ''
    if (days === 0) return '今天到期'
    if (days === 1) return '明天到期'
    if (days <= 7) return `${days} 天后到期`
    return `${Math.round(days / 7)} 周后到期`
  },
})

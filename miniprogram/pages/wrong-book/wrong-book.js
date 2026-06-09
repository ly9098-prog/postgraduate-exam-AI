const api = require('../../utils/api')
const config = require('../../config')

Page({
  data: {
    filter: 'unmastered',
    list: [],
    stats: {},
    page: 1,
    hasMore: false,
    loading: false,
    enableMathImage: false,
  },

  onLoad() {
    this.setData({ enableMathImage: config.enableMathImage || false })
  },

  onShow() {
    this.setData({ list: [], page: 1 })
    this.loadStats()
    this.loadList(true)
  },

  async loadStats() {
    try {
      const stats = await api.get('/wrong-questions/stats')
      this.setData({ stats })
    } catch (e) {
      console.error('加载错题统计失败', e)
    }
  },

  async loadList(reset = false) {
    const page = reset ? 1 : this.data.page
    this.setData({ loading: true })

    try {
      const params = { page, page_size: 20 }
      if (this.data.filter === 'unmastered') params.mastered = false
      if (this.data.filter === 'mastered') params.mastered = true

      const data = await api.get('/wrong-questions', params)
      this.setData({
        list: reset ? data.items : [...this.data.list, ...data.items],
        hasMore: page < data.total_pages,
        page: page + 1,
        loading: false,
      })
    } catch (e) {
      console.error('加载错题列表失败', e)
      this.setData({ loading: false })
    }
  },

  switchFilter(e) {
    var ds = e.currentTarget && e.currentTarget.dataset
    var filter = (ds && ds.filter) || e
    this.setData({ filter: filter, list: [], page: 1 })
    this.loadList(true)
  },

  loadMore() {
    this.loadList()
  },

  goDetail(e) {
    const ids = this.data.list.map(item => item.id).join(',')
    wx.navigateTo({
      url: `/pages/wrong-detail/wrong-detail?id=${e.currentTarget.dataset.id}&ids=${ids}`,
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

  errorTypeLabel(t) {
    const map = { concept_mistake: '概念', calculation: '计算', careless: '粗心', method: '方法', other: '其他' }
    return map[t] || t
  },
})

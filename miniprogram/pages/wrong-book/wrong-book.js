const api = require('../../utils/api')

Page({
  data: {
    filter: 'unmastered',
    list: [],
    stats: {},
    page: 1,
    hasMore: false,
    loading: false,
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
    const filter = e.currentTarget?.dataset?.filter || e
    this.setData({ filter, list: [], page: 1 })
    this.loadList(true)
  },

  loadMore() {
    this.loadList()
  },

  goDetail(e) {
    wx.navigateTo({
      url: `/pages/wrong-detail/wrong-detail?id=${e.currentTarget.dataset.id}`,
    })
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s
  },

  errorTypeLabel(t) {
    const map = { concept_mistake: '概念', calculation: '计算', careless: '粗心', method: '方法', other: '其他' }
    return map[t] || t
  },
})

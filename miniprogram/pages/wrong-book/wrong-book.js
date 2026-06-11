const api = require('../../utils/api')
const config = require('../../config')

const SUBJECTS = [
  { value: '', label: '全部' },
  { value: 'math2', label: '数学二' },
  { value: 'math2-calculus', label: '高数' },
  { value: 'math2-linalg', label: '线代' },
  { value: 'exam408', label: '408' },
  { value: 'english', label: '英语' },
]

const ERROR_TYPES = [
  { value: '', label: '全部类型' },
  { value: 'concept_mistake', label: '概念错误' },
  { value: 'calculation', label: '计算错误' },
  { value: 'careless', label: '粗心' },
  { value: 'method', label: '方法错误' },
  { value: 'other', label: '其他' },
]

Page({
  data: {
    list: [],
    stats: { total: 0 },
    page: 1,
    hasMore: false,
    loading: false,
    enableMathImage: false,

    // filters
    selectedSubject: '',
    selectedErrorType: '',
    showFilter: false,

    subjects: SUBJECTS,
    errorTypes: ERROR_TYPES,
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
      if (this.data.selectedSubject) params.subject = this.data.selectedSubject
      if (this.data.selectedErrorType) params.error_type = this.data.selectedErrorType

      const data = await api.get('/wrong-questions', params)

      const items = (data.items || []).map(item => ({
        ...item,
        _subjectLabel: this._subjectLabel(item.subject),
        _errorTypeLabel: this._errorTypeLabel(item.error_type),
        _timeLabel: this._timeLabel(item.created_at),
        _cleanText: item.content ? this._toCleanText(item.content.text || item.content) : '',
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

  toggleFilter() {
    this.setData({ showFilter: !this.data.showFilter })
  },

  selectSubject(e) {
    const val = e.currentTarget.dataset.value
    this.setData({ selectedSubject: val, list: [], page: 1 })
    this.loadList(true)
  },

  selectErrorType(e) {
    const val = e.currentTarget.dataset.value
    this.setData({ selectedErrorType: val, list: [], page: 1 })
    this.loadList(true)
  },

  loadMore() {
    this.loadList()
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id
    const ids = this.data.list.map(item => item.id).join(',')
    wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}&ids=${ids}` })
  },

  _subjectLabel(s) {
    const map = {
      math2: '数学二', 'math2-calculus': '数学二·高数', 'math2-linalg': '数学二·线代',
      exam408: '408', 'exam408-ds': '408·DS', 'exam408-os': '408·OS',
      'exam408-co': '408·CO', 'exam408-cn': '408·CN',
      english: '英语',
    }
    return map[s] || s || '未知'
  },

  _errorTypeLabel(t) {
    const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他' }
    return map[t] || t || '未知'
  },

  _timeLabel(dateStr) {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    const now = new Date()
    const diff = now - d
    const days = Math.floor(diff / 86400000)
    if (days === 0) return '今天'
    if (days === 1) return '昨天'
    if (days <= 7) return `${days} 天前`
    const m = d.getMonth() + 1
    const day = d.getDate()
    return `${m}月${day}日`
  },

  /** 剥离 LaTeX $ 符号，显示可读的纯文本预览 */
  _toCleanText(text) {
    if (!text || typeof text !== 'string') return ''
    return String(text)
      .replace(/\$\$([\s\S]*?)\$\$/g, '$1')
      .replace(/\$([^$\n]+?)\$/g, '$1')
      .replace(/\\leq/g, '≤')
      .replace(/\\geq/g, '≥')
      .replace(/\\lt/g, '<')
      .replace(/\\gt/g, '>')
      .trim()
  },
})

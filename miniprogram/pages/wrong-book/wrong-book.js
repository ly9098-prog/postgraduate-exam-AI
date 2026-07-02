const api = require('../../utils/api')
const config = require('../../config')
const { toPlainInlineMathText } = require('../../utils/stem-render')

const SUBJECTS = [
  { value: '', label: '全部' },
  // 新树形科目
  { value: 'math', label: '数学' },
  { value: 'advanced_math', label: '高数' },
  { value: 'linear_algebra', label: '线性代数' },
  { value: 'computer', label: '计算机' },
  { value: 'ds', label: '数据结构' },
  { value: 'os', label: '操作系统' },
  { value: 'co', label: '计组' },
  { value: 'cn', label: '网络' },
  { value: 'english', label: '英语' },
  { value: 'politics', label: '政治' },
  // 旧兼容科目
  { value: 'math2', label: '数学二' },
  { value: 'math2-calculus', label: '高数(旧)' },
  { value: 'math2-linalg', label: '线代(旧)' },
  { value: 'exam408', label: '408' },
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
    primaryStatCount: 0,
    primaryStatLabel: '错题总数',
    analysis: {
      sourceLabel: '待积累',
      weaknessTags: [],
      radarItems: [],
      subjectItems: [],
      summaryCards: [],
      actionPlan: [],
    },
    aiDiagnosis: null,
    aiDiagnosisLoading: false,
    page: 1,
    hasMore: false,
    loading: false,
    enableMathImage: false,

    // filters
    selectedSubject: '',
    selectedErrorType: '',
    selectedTopic: '',
    showFilter: false,

    subjects: SUBJECTS,
    errorTypes: ERROR_TYPES,
  },

  _ready: false,

  onLoad(options) {
    this.setData({ enableMathImage: config.enableMathImage || false })
    // 从 dashboard 跳转携带 subject 或 topic 参数
    const subject = options.subject ? decodeURIComponent(options.subject) : ''
    const topic = options.topic ? decodeURIComponent(options.topic) : ''
    if (subject) {
      this.setData({ selectedSubject: subject })
    }
    if (topic) {
      this.setData({ selectedTopic: topic })
    }
  },

  onReady() {
    this._ready = true
    this._loadPage()
  },

  onShow() {
    if (!this._ready) return
    this._loadPage()
  },

  _loadPage() {
    this.setData({ list: [], page: 1 })
    this.loadStats()
    this.loadList(true)
    this.loadAiDiagnosis()
  },

  async loadStats() {
    try {
      const stats = await api.get('/wrong-questions/stats')
      this.setData({
        stats,
        primaryStatCount: typeof stats.unmastered === 'number' ? stats.unmastered : (stats.total || 0),
        primaryStatLabel: typeof stats.unmastered === 'number' ? '待攻克错题' : '错题总数',
      })
      // Rebuild analysis with fresh stats when no filter is active
      const hasFilter = this.data.selectedSubject || this.data.selectedErrorType || this.data.selectedTopic
      if (!hasFilter && this.data.list.length > 0) {
        this.setData({ analysis: this._buildAnalysis(stats, this.data.list) })
      }
    } catch (e) {
      console.error('加载错题统计失败', e)
    }
  },

  async loadAiDiagnosis() {
    this.setData({ aiDiagnosisLoading: true, aiDiagnosis: null })
    try {
      const diagnosis = await api.get('/stats/ai-diagnosis')
      if (diagnosis) {
        // Guard against null/missing array fields from backend
        for (const listKey of ['weak_points', 'strong_points', 'learning_suggestions']) {
          if (!Array.isArray(diagnosis[listKey])) diagnosis[listKey] = []
        }
        // Enrich accuracy percent for weak/strong points
        for (const listKey of ['weak_points', 'strong_points']) {
          diagnosis[listKey] = diagnosis[listKey].map(item => ({
            ...item,
            _accuracyPercent: Math.round((item.accuracy || 0) * 100),
          }))
        }
      }
      if (diagnosis && (diagnosis.weak_points.length > 0 || diagnosis.strong_points.length > 0 || diagnosis.learning_suggestions.length > 0 || diagnosis.summary)) {
        this.setData({ aiDiagnosis: diagnosis, aiDiagnosisLoading: false })
      } else {
        this.setData({ aiDiagnosisLoading: false, aiDiagnosis: null })
      }
    } catch (e) {
      console.error('加载AI诊断失败', e)
      this.setData({ aiDiagnosisLoading: false })
    }
  },

  async loadList(reset = false) {
    const page = reset ? 1 : this.data.page
    this.setData({ loading: true })

    try {
      const params = { page, page_size: 20 }
      if (this.data.selectedSubject) params.subject = this.data.selectedSubject
      if (this.data.selectedErrorType) params.error_type = this.data.selectedErrorType
      if (this.data.selectedTopic) params.topic = this.data.selectedTopic

      const data = await api.get('/wrong-questions', params)

      const items = (data.items || []).map(item => this._decorateItem(item))
      const nextList = reset ? items : [...this.data.list, ...items]

      // When filter is active, build analysis from current list only (not global stats)
      const hasFilter = this.data.selectedSubject || this.data.selectedErrorType || this.data.selectedTopic
      const statsForAnalysis = hasFilter ? {} : (this.data.stats || {})
      this.setData({
        list: nextList,
        analysis: this._buildAnalysis(statsForAnalysis, nextList),
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

  clearTopic() {
    this.setData({ selectedTopic: '', list: [], page: 1 })
    this.loadList(true)
  },

  loadMore() {
    if (this.data.loading || !this.data.hasMore) return
    this.loadList()
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id
    const ids = this.data.list.map(item => item.id)
    const idx = ids.indexOf(id)
    wx.setStorageSync('wrong_detail_ids', ids)
    wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}&idx=${idx}` })
  },

  _decorateItem(item) {
    const wrongCount = this._positiveNumber(
      item.wrong_count || item.error_count || item.mistake_count || item.incorrect_count,
      1
    )
    const reviewCount = this._positiveNumber(item.review_count, 0)
    const lastErrorAt = item.last_wrong_at || item.last_error_at || item.updated_at || item.created_at
    const mastery = this._masteryProgress(item, reviewCount)

    return {
      ...item,
      _subjectLabel: this._subjectLabel(item.subject),
      _errorTypeLabel: this._errorTypeLabel(item.error_type),
      _timeLabel: this._timeLabel(item.created_at),
      _lastErrorLabel: this._timeLabel(lastErrorAt) || '待记录',
      _wrongCount: wrongCount,
      _reviewCount: reviewCount,
      _masteryPercent: mastery.percent,
      _masteryLabel: mastery.label,
      _cleanText: item.content ? this._toCleanText(item.content.text || item.content) : '',
    }
  },

  _buildAnalysis(stats = {}, list = []) {
    stats = stats || {}
    const errorRows = this._rowsFromStats(stats, ['by_error_type', 'error_types', 'errors'])
    const subjectRows = this._rowsFromStats(stats, ['by_subject', 'subjects'])
    const errorCounts = errorRows.length ? errorRows : this._countsFromList(list, 'error_type')
    const subjectCounts = subjectRows.length ? subjectRows : this._countsFromList(list, 'subject')
    const sourceLabel = errorRows.length || subjectRows.length ? '按错因统计' : (list.length ? '按当前列表统计' : '待积累')

    const weaknessTags = this._topItems(errorCounts, 5).map(row => ({
      key: row.key,
      label: this._errorTypeLabel(row.key),
      count: row.count,
    }))
    const radarItems = this._toPercentItems(this._topItems(errorCounts, 4), this._errorTypeLabel.bind(this))
    const subjectItems = this._toPercentItems(this._topItems(subjectCounts, 4), this._subjectLabel.bind(this))

    return {
      sourceLabel,
      weaknessTags,
      radarItems,
      subjectItems,
      summaryCards: this._buildSummaryCards(stats, list, weaknessTags),
      actionPlan: this._buildActionPlan(weaknessTags, subjectItems, list),
      radarPolygonStyle: this._radarPolygonStyle(radarItems),
      radarAxisText: this._radarAxisText(radarItems),
      focusInsight: this._focusInsight(weaknessTags, subjectItems, list),
    }
  },

  _buildSummaryCards(stats = {}, list = [], weaknessTags = []) {
    stats = stats || {}
    const unmastered = this._positiveNumber(stats.unmastered, this.data.primaryStatCount || stats.total || list.length || 0)
    const reviewed = list.filter(item => this._positiveNumber(item._reviewCount, 0) > 0).length
    const avgMastery = list.length
      ? Math.round(list.reduce((sum, item) => sum + this._positiveNumber(item._masteryPercent, 0), 0) / list.length)
      : 0
    const topWeakness = weaknessTags[0] ? weaknessTags[0].label : '待积累'

    return [
      { key: 'unmastered', value: unmastered, label: '待攻克', tone: 'danger' },
      { key: 'weakness', value: topWeakness, label: '首要弱项', tone: 'blue' },
      { key: 'reviewed', value: `${reviewed}/${list.length || 0}`, label: '已复盘', tone: 'success' },
      { key: 'mastery', value: `${avgMastery}%`, label: '平均掌握', tone: 'gold' },
    ]
  },

  _buildActionPlan(weaknessTags = [], subjectItems = [], list = []) {
    if (!list.length && !weaknessTags.length && !subjectItems.length) return []
    const firstWeakness = weaknessTags[0]
    const firstSubject = subjectItems[0]
    const lowMasteryCount = list.filter(item => this._positiveNumber(item._masteryPercent, 0) < 40).length
    return [
      {
        key: 'weakness',
        title: firstWeakness ? `优先复盘「${firstWeakness.label}」` : '先完成一组错题复盘',
        desc: firstWeakness ? `${firstWeakness.count} 道题集中暴露该问题` : '积累数据后会生成更明确的弱项计划',
      },
      {
        key: 'subject',
        title: firstSubject ? `重点看 ${firstSubject.label}` : '按学科建立错题节奏',
        desc: firstSubject ? `${firstSubject.count} 道错题集中在该方向` : '筛选学科后可缩小复盘范围',
      },
      {
        key: 'mastery',
        title: lowMasteryCount > 0 ? `先攻克 ${lowMasteryCount} 道低掌握题` : '保持复盘节奏',
        desc: lowMasteryCount > 0 ? '掌握进度低于 40% 的题建议优先重做' : '当前列表掌握度较稳定，适合做限时巩固',
      },
    ]
  },

  _rowsFromStats(stats, keys) {
    for (const key of keys) {
      const value = stats && stats[key]
      if (Array.isArray(value)) {
        return value.map(row => ({
          key: row.key || row.type || row.error_type || row.subject || row.name || row.label || '',
          count: this._positiveNumber(row.count || row.total || row.value, 0),
        })).filter(row => row.key && row.count > 0)
      }
      if (value && typeof value === 'object') {
        return Object.keys(value).map(k => ({ key: k, count: this._positiveNumber(value[k], 0) }))
          .filter(row => row.key && row.count > 0)
      }
    }
    return []
  },

  _countsFromList(list, field) {
    const counts = {}
    list.forEach(item => {
      const key = item[field] || 'unknown'
      counts[key] = (counts[key] || 0) + 1
    })
    return Object.keys(counts).map(key => ({ key, count: counts[key] }))
  },

  _topItems(rows, limit) {
    return rows
      .filter(row => row.key && row.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, limit)
  },

  _toPercentItems(rows, labelFn) {
    const max = rows.reduce((m, row) => Math.max(m, row.count), 0) || 1
    return rows.map(row => ({
      key: row.key,
      label: labelFn(row.key),
      count: row.count,
      percent: Math.max(12, Math.round((row.count / max) * 100)),
      height: Math.max(46, Math.round((row.count / max) * 100) + 34),
    }))
  },

  _radarPolygonStyle(items = []) {
    if (!items.length) return ''
    const points = [
      [50, 50 - items[0].percent * 0.42],
      [50 + (items[1] ? items[1].percent : items[0].percent) * 0.42, 50],
      [50, 50 + (items[2] ? items[2].percent : items[0].percent) * 0.42],
      [50 - (items[3] ? items[3].percent : items[0].percent) * 0.42, 50],
    ]
    return `clip-path: polygon(${points.map(point => `${Math.round(point[0])}% ${Math.round(point[1])}%`).join(', ')});`
  },

  _radarAxisText(items = []) {
    if (!items.length) return '暂无能力图谱数据'
    return items.map(item => `${item.label}${item.count}题`).join('，')
  },

  _focusInsight(weaknessTags = [], subjectItems = [], list = []) {
    const weakness = weaknessTags[0]
    const subject = subjectItems[0]
    if (weakness && subject) return `${subject.label}的「${weakness.label}」最需要优先攻克`
    if (weakness) return `优先攻克「${weakness.label}」相关错题`
    if (list.length) return '当前错题已形成复盘样本，建议先完成一轮筛选复盘'
    return '错题数据积累后，将生成知识漏洞诊断。'
  },

  _masteryProgress(item, reviewCount) {
    const raw = item.mastery_progress || item.mastery_percent || item.mastery
    if (raw !== undefined && raw !== null && raw !== '') {
      const percent = Math.max(0, Math.min(100, Number(raw) > 1 ? Number(raw) : Number(raw) * 100))
      return { percent: Math.round(percent), label: percent >= 80 ? '接近掌握' : percent >= 40 ? '巩固中' : '待攻克' }
    }

    const percent = Math.min(90, reviewCount * 20)
    return { percent, label: reviewCount > 0 ? '按复习次数估算' : '待复习' }
  },

  _positiveNumber(value, fallback) {
    const n = Number(value)
    if (!Number.isFinite(n) || n < 0) return fallback
    return Math.round(n)
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
    const map = { concept_mistake: '概念错误', calculation: '计算错误', careless: '粗心', method: '方法错误', other: '其他', unknown: '未分类' }
    return map[t] || t || '未知'
  },

  _timeLabel(dateStr) {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    if (Number.isNaN(d.getTime())) return ''
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

  _toCleanText(text) {
    if (!text || typeof text !== 'string') return ''
    const plain = toPlainInlineMathText(text)
    return plain !== null ? plain : String(text).replace(/\n/g, ' ')
  },
})

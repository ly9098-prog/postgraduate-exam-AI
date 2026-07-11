const api = require('../../utils/api')
const config = require('../../config')
const { toPlainInlineMathText } = require('../../utils/stem-render')
const storage = require('../../utils/storage')
const aiCache = require('../../utils/ai-diagnosis-cache')
const { getSubjectName, getSubjectShortName } = require('../../utils/subject-meta')

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
    masteredCount: 0,
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
    aiDiagnosisRefreshing: false,
    aiDiagnosisCacheTimeLabel: '',
    aiDiagnosisCacheStale: false,
    aiDiagnosisError: false,
    page: 1,
    hasMore: false,
    loading: false,
    enableMathImage: false,

    // filters
    selectedSubject: '',
    selectedErrorType: '',
    selectedTopic: '',
    showFilter: false,
    filterCount: 0,

    subjects: SUBJECTS,
    errorTypes: ERROR_TYPES,
  },

  _updateFilterCount() {
    const count = (this.data.selectedSubject ? 1 : 0) + (this.data.selectedErrorType ? 1 : 0) + (this.data.selectedTopic ? 1 : 0)
    this.setData({ filterCount: count })
  },

  _ready: false,
  _alive: false,
  _aiDiagnosisPromise: null,
  _aiDiagnosisRequestId: 0,
  _aiDiagnosisCachedAt: 0,
  _aiStatsLoaded: false,
  _listRequestSeq: 0,

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
    this._updateFilterCount()

    // 尽早恢复缓存，使页面首次渲染时直接显示已有诊断
    this._restoreAiDiagnosisFromCache()
  },

  onReady() {
    this._ready = true
    this._loadPage()
  },

  onShow() {
    this._alive = true
    if (!this._ready) return
    // 刷新统计和列表，但不无条件刷新 AI
    this.loadStats()
    this.loadList(true)
    // 已有诊断时检查是否需要后台更新
    // 无诊断时由 _loadPage / _checkAiDiagnosis 处理
    if (this.data.aiDiagnosis) {
      this._checkAiDiagnosis()
    }
  },

  onHide() {
    this._alive = false
  },

  onUnload() {
    this._alive = false
  },

  // ════════════════════════════════════════════
  // Page loading
  // ════════════════════════════════════════════

  async _loadPage() {
    this.setData({ list: [], page: 1 })
    await Promise.all([
      this.loadStats(),
      this.loadList(true),
    ])
    // 首次加载完成后检查 AI 诊断
    await this._checkAiDiagnosis()
  },

  _restoreAiDiagnosisFromCache() {
    var user = this._getUser()
    var userId = user && (user.id || user.user_id || user.openid || '')
    var cache = aiCache.restore(userId)
    if (cache.status !== 'miss' && cache.data) {
      this._aiDiagnosisCachedAt = cache.cachedAt
      this.setData({
        aiDiagnosis: cache.data,
        aiDiagnosisCacheTimeLabel: aiCache.formatCacheTime(cache.cachedAt),
        aiDiagnosisCacheStale: cache.status === 'stale',
        aiDiagnosisError: false,
        aiDiagnosisLoading: false,
        aiDiagnosisRefreshing: false,
      })
    }
  },

  async loadStats() {
    try {
      const stats = await api.get('/wrong-questions/stats')
      this._aiStatsLoaded = true
      const masteredCount = typeof stats.unmastered === 'number' ? Math.max(0, (stats.total || 0) - stats.unmastered) : 0
      this.setData({
        stats,
        primaryStatCount: typeof stats.unmastered === 'number' ? stats.unmastered : (stats.total || 0),
        masteredCount,
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

  async loadList(reset = false) {
    const page = reset ? 1 : this.data.page
    const seq = ++this._listRequestSeq
    this.setData({ loading: true })

    try {
      const params = { page, page_size: 20 }
      if (this.data.selectedSubject) params.subject = this.data.selectedSubject
      if (this.data.selectedErrorType) params.error_type = this.data.selectedErrorType
      if (this.data.selectedTopic) params.topic = this.data.selectedTopic

      const data = await api.get('/wrong-questions', params)

      // Stale response guard
      if (seq !== this._listRequestSeq || !this._alive) return

      const items = (data.items || []).map(item => this._decorateItem(item))
      const nextList = reset ? items : [...this.data.list, ...items]

      // When filter is active, build analysis from current list only (not global stats)
      const hasFilter = this.data.selectedSubject || this.data.selectedErrorType || this.data.selectedTopic
      const statsForAnalysis = hasFilter ? {} : (this.data.stats || {})
      if (seq !== this._listRequestSeq || !this._alive) return
      this.setData({
        list: nextList,
        analysis: this._buildAnalysis(statsForAnalysis, nextList),
        hasMore: page < data.total_pages,
        page: reset ? 2 : page + 1,
        loading: false,
      })
    } catch (e) {
      console.error('加载错题列表失败', e)
      if (seq === this._listRequestSeq && this._alive) {
        this.setData({ loading: false })
      }
    }
  },

  toggleFilter() {
    this.setData({ showFilter: !this.data.showFilter })
  },

  selectSubject(e) {
    const val = e.currentTarget.dataset.value
    this._listRequestSeq++
    this.setData({ selectedSubject: val, list: [], page: 1, loading: true })
    this._updateFilterCount()
    this.loadList(true)
  },

  selectErrorType(e) {
    const val = e.currentTarget.dataset.value
    this._listRequestSeq++
    this.setData({ selectedErrorType: val, list: [], page: 1, loading: true })
    this._updateFilterCount()
    this.loadList(true)
  },

  clearTopic() {
    this._listRequestSeq++
    this.setData({ selectedTopic: '', list: [], page: 1, loading: true })
    this._updateFilterCount()
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
    wx.setStorageSync('wrong_detail_nav', { ids, ts: Date.now() })
    wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}&idx=${idx}&source=wrong-book` })
  },

  // ════════════════════════════════════════════
  // AI 诊断缓存管理
  // ════════════════════════════════════════════

  _getUser() {
    try { return storage.get(storage.KEYS.USER) } catch (_) { return null }
  },

  _getUserId() {
    var user = this._getUser()
    return user && (user.id || user.user_id || user.openid || '')
  },

  /**
   * 标准化 AI 诊断数据
   */
  _normalizeAiDiagnosis(raw) {
    if (!raw) return null
    var copy = JSON.parse(JSON.stringify(raw))
    for (var listKey of ['weak_points', 'strong_points', 'learning_suggestions']) {
      if (!Array.isArray(copy[listKey])) copy[listKey] = []
    }
    for (var key of ['weak_points', 'strong_points']) {
      copy[key] = copy[key].map(function(item) {
        if (!item || typeof item !== 'object') return null
        var acc = item.accuracy
        if (typeof acc !== 'number') acc = 0
        if (acc > 1) acc = Math.min(acc, 100)
        var pct = acc <= 1 ? Math.round(acc * 100) : Math.round(acc)
        pct = Math.max(0, Math.min(100, pct))
        return {
          knowledge_point: String(item.knowledge_point || ''),
          accuracy: acc,
          _accuracyPercent: pct,
          suggestion: String(item.suggestion || ''),
        }
      }).filter(function(item) { return item && item.knowledge_point })
    }
    copy.learning_suggestions = copy.learning_suggestions.filter(function(s) { return s && String(s).trim() })
    return copy
  },

  /**
   * 构建数据指纹
   */
  _buildAiDiagnosisSourceSignature() {
    var stats = this.data.stats || {}
    var list = this.data.list || []
    var firstItem = list[0] || {}
    return aiCache.buildSignature(stats, list)
  },

  /**
   * 检查 AI 诊断状态，决定是否需要请求
   * 安全：不因为 stats 未加载就清除已有诊断
   */
  async _checkAiDiagnosis() {
    var stats = this.data.stats || {}
    var total = stats.total
    // stats 尚未加载成功时，不基于初始值 { total: 0 } 做任何判断
    if (!this._aiStatsLoaded) {
      return this.data.aiDiagnosis || null
    }
    // 明确知道 total = 0
    if (total === 0) {
      if (this.data.aiDiagnosis) {
        var uid = this._getUserId()
        aiCache.clear(uid)
        this.setData({
          aiDiagnosis: null,
          aiDiagnosisLoading: false,
          aiDiagnosisRefreshing: false,
          aiDiagnosisCacheTimeLabel: '',
          aiDiagnosisCacheStale: false,
          aiDiagnosisError: false,
        })
      }
      return null
    }

    return this.ensureAiDiagnosis({ background: true })
  },

  /**
   * 统一 AI 诊断入口
   * @param {object} options
   *   force:     true = 忽略缓存和指纹，强制请求（手动刷新）
   *   background: true = 后台刷新，失败时静默
   */
  async ensureAiDiagnosis(options) {
    options = options || {}

    // 无错题 → 不请求（仅在 stats 已明确加载时）
    if (this._aiStatsLoaded) {
      var total = (this.data.stats || {}).total
      if (total === 0) return null
    }

    // 已有请求正在进行 → 复用
    if (this._aiDiagnosisPromise) return this._aiDiagnosisPromise

    // 强制刷新（手动）→ 直接请求
    if (options.force) {
      return this._requestAiDiagnosis({ force: true })
    }

    // 检查缓存状态
    var hasData = !!this.data.aiDiagnosis

    if (hasData && !options.background) {
      // 已有诊断，非后台 → 直接使用，不请求
      return this.data.aiDiagnosis
    }

    // 后台刷新场景：检查 TTL 和指纹
    var needRefresh = false
    if (!hasData) {
      needRefresh = true
    } else {
      var isStale = this.data.aiDiagnosisCacheStale
      var cachedAt = this._aiDiagnosisCachedAt
      // 过期 → 刷新
      if (isStale) {
        needRefresh = true
      } else {
        // 检查指纹变化
        var currentSig = this._buildAiDiagnosisSourceSignature()
        // 从缓存读取上一次指纹
        var uid = this._getUserId()
        var cache = aiCache.restore(uid)
        if (cache.signature && cache.signature !== currentSig && aiCache.canRefresh(cachedAt)) {
          needRefresh = true
        }
      }
    }

    if (!needRefresh) {
      return this.data.aiDiagnosis
    }

    return this._requestAiDiagnosis({ background: true })
  },

  /**
   * 实际请求 AI 诊断
   */
  async _requestAiDiagnosis(opts) {
    var self = this
    opts = opts || {}
    var hasData = !!this.data.aiDiagnosis
    var requestId = ++this._aiDiagnosisRequestId

    // 设置 loading 状态
    if (!hasData) {
      this.setData({ aiDiagnosisLoading: true, aiDiagnosisError: false })
    } else {
      this.setData({ aiDiagnosisRefreshing: true, aiDiagnosisError: false })
    }

    this._aiDiagnosisPromise = (async function() {
      try {
        var diagnosis = await api.get('/stats/ai-diagnosis')
        // 过期响应保护
        if (requestId !== self._aiDiagnosisRequestId || !self._alive) return self.data.aiDiagnosis

        var normalized = self._normalizeAiDiagnosis(diagnosis)

        var hasContent = normalized && !!(
          (normalized.summary && String(normalized.summary).trim()) ||
          normalized.weak_points.length > 0 ||
          normalized.strong_points.length > 0 ||
          normalized.learning_suggestions.length > 0
        )

        if (hasContent) {
          var sig = self._buildAiDiagnosisSourceSignature()
          var uid = self._getUserId()
          var now = Date.now()
          self._aiDiagnosisCachedAt = now
          // 写入缓存
          aiCache.save(uid, normalized, sig)
          self.setData({
            aiDiagnosis: normalized,
            aiDiagnosisLoading: false,
            aiDiagnosisRefreshing: false,
            aiDiagnosisCacheTimeLabel: aiCache.formatCacheTime(now),
            aiDiagnosisCacheStale: false,
            aiDiagnosisError: false,
          })
          return normalized
        }

        // 接口返回空 — 有旧结果则保留
        if (hasData) {
          self.setData({
            aiDiagnosisLoading: false,
            aiDiagnosisRefreshing: false,
          })
          return self.data.aiDiagnosis
        }

        self.setData({
          aiDiagnosis: null,
          aiDiagnosisLoading: false,
          aiDiagnosisRefreshing: false,
          aiDiagnosisError: true,
        })
        return null
      } catch (e) {
        console.error('加载 AI 诊断失败', e)
        if (requestId !== self._aiDiagnosisRequestId || !self._alive) return self.data.aiDiagnosis

        // 有旧结果 → 保留
        if (hasData) {
          self.setData({
            aiDiagnosisLoading: false,
            aiDiagnosisRefreshing: false,
          })
          // 手动刷新才弹 Toast
          if (opts.force) {
            wx.showToast({ title: '更新失败，请稍后重试', icon: 'none' })
          }
          return self.data.aiDiagnosis
        }

        // 无旧结果 → 显示错误态
        self.setData({
          aiDiagnosis: null,
          aiDiagnosisLoading: false,
          aiDiagnosisRefreshing: false,
          aiDiagnosisError: true,
        })
        return null
      } finally {
        self._aiDiagnosisPromise = null
      }
    })()

    return this._aiDiagnosisPromise
  },

  /**
   * 手动重新分析
   */
  refreshAiDiagnosis() {
    if (this._aiDiagnosisPromise) {
      wx.showToast({ title: '正在更新中...', icon: 'none' })
      return
    }
    if (this._aiStatsLoaded) {
      var total = (this.data.stats || {}).total
      if (total === 0) {
        wx.showToast({ title: '暂无错题数据', icon: 'none' })
        return
      }
    }
    this.ensureAiDiagnosis({ force: true })
  },

  onAiFeedback() {
    var types = ['分析不准确', '遗漏薄弱点', '建议不合理', '其他问题']
    wx.showActionSheet({
      itemList: types,
      success: function (res) {
        var feedbackType = types[res.tapIndex] || '其他问题'
        api.post('/ai/feedback', {
          source: 'wrong_book',
          feedback_type: feedbackType,
        }).then(function () {
          wx.showToast({ title: '反馈已提交，感谢您的帮助', icon: 'success' })
        }).catch(function () {
          wx.showToast({ title: '反馈提交失败，请稍后重试', icon: 'none' })
        })
      },
    })
  },

  // ════════════════════════════════════════════
  // Decorators & Analysis (unchanged)
  // ════════════════════════════════════════════

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
    const hasStats = Object.keys(stats).length > 0
    const unmastered = hasStats
      ? this._positiveNumber(stats.unmastered, stats.total || list.length || 0)
      : list.length
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
    return getSubjectName(s)
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

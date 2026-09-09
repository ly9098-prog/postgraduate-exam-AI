const api = require('../../../utils/api')
const { buildKnowledgeGroups } = require('./tree-groups')
const { POINTS_PER_PAGE, buildScene, fitCamera, cameraLimits, clampCamera, zoomCamera, cameraStyle } = require('./graph-layout')

const STATUS_TEXT = { no_data: '未开始', insufficient: '数据不足', weak: '薄弱', developing: '提升中', good: '良好', mastered: '已掌握' }
const FILTERS = [
  { id: 'all', label: '全部' }, { id: 'weak', label: '需强化', statuses: ['weak', 'developing'] },
  { id: 'unseen', label: '待建立', statuses: ['no_data', 'insufficient'] },
  { id: 'mastered', label: '较稳定', statuses: ['good', 'mastered'] },
]
const INITIAL_INDEX_LIMIT = 12
const QUICK_THEME_LIMIT = 5
const RECENT_THEME_LIMIT = 5
const SEARCH_DEBOUNCE_MS = 280
const THEME_SHEET_SELECT_DELAY_MS = 96
const THEME_SHEET_CLOSE_MS = 236
const THEME_TRANSITION_MS = 240
const LABEL_SWITCH_OUT_MS = 34
const CAMERA_FRAME_MS = 16
const PAN_THRESHOLD = 5
const INERTIA_MIN_SPEED = 0.025
const INERTIA_DECAY = 0.91
const SEARCH_SEPARATOR_RE = /[\s\-_/\\·•,，。.;；:：()（）[\]【】{}<>《》'"“”‘’]+/g
const nonnegative = value => Math.max(0, Number(value) || 0)
const normalizeSearchText = value => String(value || '').trim().toLowerCase()
const compactSearchText = value => normalizeSearchText(value).replace(SEARCH_SEPARATOR_RE, '')
const searchTokens = value => normalizeSearchText(value).split(SEARCH_SEPARATOR_RE).filter(Boolean)
const pointSearchMatch = (node, query) => {
  const rawQuery = normalizeSearchText(query)
  if (!rawQuery) return { matched: true, alias: '' }
  const compactQuery = compactSearchText(rawQuery)
  const tokens = searchTokens(rawQuery)
  const raw = normalizeSearchText(node && node.name)
  if (!raw) return { matched: false, alias: '' }
  const compact = compactSearchText(raw)
  const matched = raw.includes(rawQuery) || (compactQuery && compact.includes(compactQuery)) || (tokens.length > 1 && tokens.every(token => raw.includes(token) || compact.includes(compactSearchText(token))))
  return { matched: Boolean(matched), alias: '' }
}
const THEME_ICON_ASSETS = {
  overview: '/assets/icons/knowledge-subject/overview.png',
  tree: '/assets/icons/knowledge-subject/tree.png',
  nodes: '/assets/icons/knowledge-subject/nodes.png',
  relation: '/assets/icons/knowledge-subject/relation.png',
  move: '/assets/icons/knowledge-subject/move.png',
  chip: '/assets/icons/knowledge-subject/chip.png',
  queue: '/assets/icons/knowledge-subject/queue.png',
  layers: '/assets/icons/knowledge-subject/layers.png',
  code: '/assets/icons/knowledge-subject/code.png',
}
const themeIconSrc = kind => THEME_ICON_ASSETS[kind] || THEME_ICON_ASSETS.nodes

const themeIconKind = (group, index = 0) => {
  const text = `${group && group.name ? group.name : ''} ${group && group.key ? group.key : ''}`.toLowerCase()
  if (/b树|b-tree|btree|二叉|tree|树|avl/.test(text)) return 'tree'
  if (/catalan|图|graph|网络|拓扑|huffman/.test(text)) return 'nodes'
  if (/关系|共享|关联|relation|path|关键路径/.test(text)) return 'relation'
  if (/元素移动|移动|move|transfer|swap/.test(text)) return 'move'
  if (/内存|分配|memory|alloc|页|cache/.test(text)) return 'chip'
  if (/队列|queue|循环队列|广度/.test(text)) return 'queue'
  if (/入栈|出栈|栈|stack|序列|操作/.test(text)) return 'layers'
  if (/c语言|字符|标识符|code|string|kmp|search|查找|binary/.test(text)) return 'code'
  return ['nodes', 'tree', 'move', 'layers', 'code', 'relation', 'chip', 'queue'][index % 8]
}
const formatThemeOrder = (group, index = 0) => {
  const value = group && group.number != null ? String(group.number) : String(index + 1)
  const digits = value.replace(/\D+/g, '')
  return (digits || String(index + 1)).padStart(2, '0')
}
const themeSearchMatch = (group, query) => {
  const rawQuery = normalizeSearchText(query)
  if (!rawQuery) return true
  const compactQuery = compactSearchText(rawQuery)
  const candidates = [group && group.name, group && group.number]
  return candidates.some((value) => {
    const raw = normalizeSearchText(value)
    if (!raw) return false
    const compact = compactSearchText(raw)
    return raw.includes(rawQuery) || (compactQuery && compact.includes(compactQuery))
  })
}
const QUICK_THEME_PRIORITY = [
  /b树|b-tree|btree|b tree|tree/i,
  /元素移动|移动|move|transfer|swap/i,
  /入栈出栈序列|入栈|出栈|stack push|stack pop|stack/i,
  /catalan/i,
  /c语言标识符|c语言|标识符|identifier|code/i,
]
const buildQuickGroupChips = (chips, activeKey) => {
  const source = Array.isArray(chips) ? chips : []
  const picked = []
  const used = new Set()
  QUICK_THEME_PRIORITY.forEach((pattern) => {
    const hit = source.find(item => !used.has(String(item.key)) && pattern.test(String(item.name || '')))
    if (!hit) return
    picked.push(hit)
    used.add(String(hit.key))
  })
  source.forEach((item) => {
    if (picked.length >= QUICK_THEME_LIMIT) return
    const key = String(item.key)
    if (used.has(key)) return
    picked.push(item)
    used.add(key)
  })
  const result = picked.slice(0, QUICK_THEME_LIMIT)
  const normalizedActive = String(activeKey || '')
  if (!normalizedActive || result.some(item => String(item.key) === normalizedActive)) return result
  const activeItem = source.find(item => String(item.key) === normalizedActive)
  if (!activeItem) return result
  if (result.length < QUICK_THEME_LIMIT) result.push(activeItem)
  else if (result.length) result[result.length - 1] = activeItem
  return result
}
const percent = value => value == null || !Number.isFinite(Number(value)) ? null : Math.max(0, Math.min(100, Math.round(Number(value))))
const accuracyPercent = (value) => {
  const number = Number(value)
  if (value == null || !Number.isFinite(number)) return null
  return percent(Math.abs(number) <= 1 ? number * 100 : number)
}

Page({
  data: {
    loading: true, error: '', refreshError: '', subject: null, syllabusText: '',
    loadingMetrics: [1, 2, 3],
    stats: { total: 0, reliable: 0, weak: 0, coverage: 0 },
    filters: FILTERS.map(item => ({ id: item.id, label: item.label, count: 0 })),
    filter: 'all', query: '', searchFocused: false, searchPending: false, searchResultCount: 0, activeGroupKey: '', activeGroupName: '',
    groupChips: [], quickGroupChips: [], themeGroupCount: 0, themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '', themeSheetGroups: [],
    scene: { nodes: [], edges: [], page: 0, pageCount: 1, focused: false },
    pageEntered: false, sceneAnimating: false, themeSwitching: false, themeSwitchPhase: '', graphInteracting: false,
    stageStyle: '', zoomText: '100%', zoomInDisabled: false, zoomOutDisabled: true, selectedPoint: null,
    indexNodes: [], indexCount: 0, hasMore: false,
  },

  onLoad(options) {
    this.subjectId = Number(options && options.subject_id)
    let width = 375
    try {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
      width = Number(info.windowWidth) || width
    } catch (error) { /* 使用默认宽度，布局挂载后按实际容器尺寸校准。 */ }
    this._frame = { left: 0, top: 0, width: width * 702 / 750, height: width * 700 / 750 }
    this._camera = fitCamera(this._frame)
    this.setCamera(this._camera)
    if (!Number.isInteger(this.subjectId) || this.subjectId <= 0) {
      this.setData({ loading: false, error: '科目参数无效' })
      return
    }
    this._recentGroupStorageKey = `knowledgeSubjectRecentGroups:${this.subjectId}`
    try {
      const stored = wx.getStorageSync(this._recentGroupStorageKey)
      this._recentGroupKeys = Array.isArray(stored) ? stored.map(item => String(item || '')).filter(Boolean).slice(0, RECENT_THEME_LIMIT) : []
    } catch (error) { this._recentGroupKeys = [] }
    return this.loadMap()
  },

  onReady() { this.measureViewport(true) },
  onShow() { if (this._loadedOnce) this.loadMap(false) },
  onPageScroll(event) { this._scrollTop = Number(event.scrollTop) || 0 },
  onResize() { this.measureViewport(true) },
  onUnload() {
    this._unloaded = true
    this._requestId = (this._requestId || 0) + 1
    clearTimeout(this._cameraTimer)
    clearTimeout(this._inertiaTimer)
    clearTimeout(this._searchTimer)
    clearTimeout(this._entryTimer)
    clearTimeout(this._sceneAnimationTimer)
    clearTimeout(this._themeSheetCloseTimer)
    clearTimeout(this._themeSheetSelectTimer)
    clearTimeout(this._themeTransitionTimer)
    clearTimeout(this._labelSwitchTimer)
  },
  onPullDownRefresh() { return this.loadMap(false).finally(() => wx.stopPullDownRefresh()) },

  async loadMap(showLoading = true) {
    if (!Number.isInteger(this.subjectId) || this.subjectId <= 0) return
    const requestId = (this._requestId || 0) + 1
    this._requestId = requestId
    if (showLoading) this.setData({ loading: !this._loadedOnce, error: '', refreshError: '' })
    try {
      const data = await api.get(`/knowledge-map/subjects/${this.subjectId}`)
      if (this._unloaded || requestId !== this._requestId) return
      if (!data || !data.subject) throw new Error('知识图谱暂不可用')
      this._nodes = (Array.isArray(data.nodes) ? data.nodes : []).map((item) => {
        const score = percent(item.mastery_score)
        const accuracy = accuracyPercent(item.accuracy)
        const status = STATUS_TEXT[item.status] ? item.status : 'no_data'
        const aliases = Array.isArray(item.aliases)
          ? item.aliases.map(alias => String(alias || '').trim()).filter(Boolean)
          : []
        return {
          ...item, aliases, name: String(item.name || '未命名知识点'), status, statusText: STATUS_TEXT[status],
          tone: status === 'weak' || status === 'developing' ? 'weak' : (status === 'good' || status === 'mastered' ? 'stable' : 'unseen'),
          scoreText: score == null ? '待建立' : `${score}%`, hasScore: score != null,
          accuracyText: accuracy == null ? '暂无' : `${accuracy}%`,
          attempt_count: nonnegative(item.attempt_count),
          trainable_question_count: nonnegative(item.trainable_question_count),
          hasPractice: nonnegative(item.trainable_question_count) > 0,
        }
      })
      this._groups = buildKnowledgeGroups(this._nodes, data.subject)
      this._nodeById = new Map()
      this._groups.forEach(group => group.nodes.forEach(node => this._nodeById.set(Number(node.knowledge_point_id), { ...node, groupKey: group.key, groupName: group.name })))
      const total = nonnegative(data.subject.trainable_knowledge_points == null ? this._nodes.filter(node => node.hasPractice).length : data.subject.trainable_knowledge_points)
      const reliable = nonnegative(data.subject.reliable_knowledge_points)
      const weak = nonnegative(data.subject.weak_knowledge_points)
      const coverageRatio = Number(data.subject.coverage_ratio)
      const coverage = Number.isFinite(coverageRatio)
        ? percent(Math.abs(coverageRatio) <= 1 ? coverageRatio * 100 : coverageRatio)
        : (total ? percent(reliable / total * 100) : 0)
      const syllabus = data.syllabus_version
      const filters = FILTERS.map(item => ({ id: item.id, label: item.label, count: item.statuses ? this._nodes.filter(node => item.statuses.includes(node.status)).length : this._nodes.length }))
      const firstLoad = !this._loadedOnce
      this._loadedOnce = true
      wx.setNavigationBarTitle({ title: `${data.subject.subject_name} · 知识图谱` })
      this.setData({
        loading: false, error: '', refreshError: '', subject: data.subject, filters,
        syllabusText: syllabus ? [syllabus.name, syllabus.effective_year].filter(Boolean).join(' · ') : '',
        stats: { total, reliable, weak, coverage: coverage == null ? 0 : coverage },
      }, () => this.applyView(firstLoad, firstLoad, () => {
        if (firstLoad) this.enterPage()
      }))
    } catch (error) {
      if (this._unloaded || requestId !== this._requestId) return
      const message = api.getErrorMessage(error)
      this.setData(this.data.subject ? { loading: false, refreshError: message } : { loading: false, error: message })
    }
  },

  enterPage() {
    clearTimeout(this._entryTimer)
    const reveal = () => {
      this._entryTimer = setTimeout(() => {
        this._entryTimer = null
        if (!this._unloaded) this.setData({ pageEntered: true })
      }, 24)
    }
    if (wx.nextTick) wx.nextTick(reveal)
    else reveal()
  },

  applyView(resetCamera = false, animateScene = resetCamera, callback) {
    if (!this.data.subject) return
    const config = FILTERS.find(item => item.id === this.data.filter) || FILTERS[0]
    const query = normalizeSearchText(this.data.query)
    this._filteredGroups = (this._groups || []).map(group => ({
      ...group,
      nodes: group.nodes.reduce((result, node) => {
        if (config.statuses && !config.statuses.includes(node.status)) return result
        const searchMatch = pointSearchMatch(node, query)
        if (!searchMatch.matched) return result
        result.push(node)
        return result
      }, []),
    }))
    const availableGroups = this._filteredGroups.filter(group => group.nodes.length)
    const activeGroupKey = availableGroups.some(group => group.key === this.data.activeGroupKey) ? this.data.activeGroupKey : ''
    const groups = activeGroupKey ? availableGroups.filter(group => group.key === activeGroupKey) : availableGroups
    this._visibleNodes = groups.reduce((result, group) => result.concat(group.nodes), [])
    let scene = buildScene(availableGroups, this.data.subject, { groupKey: activeGroupKey, page: this._graphPage || 0, selectedId: this._selectedId })
    if (!scene.pointIds.some(id => Number(id) === Number(this._selectedId))) {
      this._selectedId = scene.pointIds.length ? Number(scene.pointIds[0]) : 0
      scene = buildScene(availableGroups, this.data.subject, { groupKey: activeGroupKey, page: scene.page, selectedId: this._selectedId })
    }
    this._graphPage = scene.page
    const limit = this._indexLimit || INITIAL_INDEX_LIMIT
    const visibleById = new Map(this._visibleNodes.map(node => [Number(node.knowledge_point_id), node]))
    const selectedBase = this._nodeById.get(this._selectedId) || null
    const selectedVisible = visibleById.get(Number(this._selectedId)) || null
    const filteredByKey = new Map((this._filteredGroups || []).map(group => [String(group.key), group]))
    const groupChips = (this._groups || []).map((group, index) => {
      const filteredGroup = filteredByKey.get(String(group.key))
      const iconKind = themeIconKind(group, index)
      return { key: String(group.key), name: group.name, count: filteredGroup ? filteredGroup.nodes.length : 0, number: group.number, orderText: formatThemeOrder(group, index), iconKind, iconSrc: themeIconSrc(iconKind) }
    })
    const quickGroupChips = buildQuickGroupChips(groupChips, activeGroupKey)
    const themeSheetGroups = groupChips.filter(group => themeSearchMatch(group, this.data.themeQuery))
    const activeGroup = groupChips.find(group => group.key === activeGroupKey)
    const payload = {
      activeGroupKey, activeGroupName: activeGroup ? activeGroup.name : '', scene,
      groupChips, quickGroupChips, themeGroupCount: groupChips.length, themeSheetGroups,
      searchPending: false,
      searchResultCount: availableGroups.reduce((count, group) => count + group.nodes.length, 0),
      selectedPoint: selectedBase,
      indexNodes: this._visibleNodes.slice(0, limit), indexCount: this._visibleNodes.length, hasMore: this._visibleNodes.length > limit,
    }
    if (animateScene) payload.sceneAnimating = true
    if (resetCamera && this._frame) {
      this.stopCameraInertia()
      this._camera = fitCamera(this._frame)
      Object.assign(payload, this.cameraPayload(true, { graphInteracting: false }))
    }
    const commit = () => this.setData(payload, () => {
      const next = () => { if (!this._unloaded) this.measureViewport(false) }
      if (wx.nextTick) wx.nextTick(next)
      else next()
      if (animateScene) {
        clearTimeout(this._sceneAnimationTimer)
        this._sceneAnimationTimer = setTimeout(() => {
          this._sceneAnimationTimer = null
          if (!this._unloaded) this.setData({ sceneAnimating: false })
        }, 820)
      }
      if (typeof callback === 'function') callback()
    })
    if (animateScene && this.data.sceneAnimating) this.setData({ sceneAnimating: false }, commit)
    else commit()
  },

  transitionLabelView(dataChanges = {}) {
    clearTimeout(this._labelSwitchTimer)
    clearTimeout(this._themeTransitionTimer)
    clearTimeout(this._sceneAnimationTimer)
    const startPayload = { ...dataChanges, sceneAnimating: false, themeSwitching: true, themeSwitchPhase: 'leaving' }
    this.setData(startPayload, () => {
      this._labelSwitchTimer = setTimeout(() => {
        this._labelSwitchTimer = null
        if (this._unloaded) return
        this.applyView(true, false, () => {
          if (this._unloaded) return
          this.setData({ themeSwitchPhase: 'entering' }, () => {
            this._themeTransitionTimer = setTimeout(() => {
              this._themeTransitionTimer = null
              if (!this._unloaded) this.setData({ themeSwitching: false, themeSwitchPhase: '' })
            }, THEME_TRANSITION_MS)
          })
        })
      }, LABEL_SWITCH_OUT_MS)
    })
  },

  setFilter(event) {
    const filter = String(event.currentTarget.dataset.filter || 'all')
    if (!FILTERS.some(item => item.id === filter) || filter === this.data.filter) return
    clearTimeout(this._searchTimer)
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    this.transitionLabelView({ filter, searchPending: false, themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' })
  },
  searchPoints(event) {
    const query = String(event.detail.value || '')
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    clearTimeout(this._searchTimer)
    const normalizedQuery = normalizeSearchText(query)
    this.setData({
      query,
      searchPending: Boolean(normalizedQuery),
      activeGroupKey: '',
      themeSheetOpen: false,
      themeSheetClosing: false,
      themeSheetPendingKey: '__idle__',
      themeQuery: '',
    })
    if (!normalizedQuery) {
      this.applyView(true, false)
      return
    }
    this._searchTimer = setTimeout(() => {
      this._searchTimer = null
      if (!this._unloaded) this.applyView(true, false)
    }, SEARCH_DEBOUNCE_MS)
  },
  focusSearch() { if (!this.data.searchFocused) this.setData({ searchFocused: true }) },
  blurSearch() { if (this.data.searchFocused) this.setData({ searchFocused: false }) },
  submitSearch(event) {
    clearTimeout(this._searchTimer)
    this._searchTimer = null
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    this.setData({ query: String(event.detail.value || ''), searchPending: false, activeGroupKey: '', themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' }, () => this.applyView(true, false))
  },
  clearSearch() {
    clearTimeout(this._searchTimer)
    this._searchTimer = null
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    this.setData({ query: '', searchPending: false, activeGroupKey: '', themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' }, () => this.applyView(true, false))
  },
  resetFilters() {
    clearTimeout(this._searchTimer)
    this._searchTimer = null
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    this.setData({ filter: 'all', query: '', searchPending: false, activeGroupKey: '', themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' }, () => this.applyView(true))
  },
  chooseGroup(event) { this.openGroup(String(event.currentTarget.dataset.key || '')) },
  rememberGroup(key) {
    const normalized = String(key || '')
    if (!normalized) return
    const next = [normalized, ...(Array.isArray(this._recentGroupKeys) ? this._recentGroupKeys : [])]
      .filter((item, index, list) => item && list.indexOf(item) === index)
      .slice(0, RECENT_THEME_LIMIT)
    this._recentGroupKeys = next
    try { if (this._recentGroupStorageKey) wx.setStorageSync(this._recentGroupStorageKey, next) } catch (error) { /* 本地偏好写入失败不影响主题切换。 */ }
  },
  openGroup(key) {
    const normalized = String(key || '')
    if (normalized && !(this._filteredGroups || []).some(group => String(group.key) === normalized && group.nodes.length)) return
    if (normalized === this.data.activeGroupKey) return
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    if (normalized) this.rememberGroup(normalized)
    const quickGroupChips = buildQuickGroupChips(this.data.groupChips, normalized)
    this.transitionLabelView({ activeGroupKey: normalized, quickGroupChips })
  },
  showOverview() { this.openGroup('') },
  openThemeSheet() {
    const groups = Array.isArray(this.data.groupChips) ? this.data.groupChips : []
    clearTimeout(this._themeSheetCloseTimer)
    clearTimeout(this._themeSheetSelectTimer)
    this.setData({ themeSheetOpen: true, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '', themeSheetGroups: groups })
  },
  finishThemeSheetClose(nextGroupKey) {
    clearTimeout(this._themeSheetCloseTimer)
    this._themeSheetCloseTimer = setTimeout(() => {
      this._themeSheetCloseTimer = null
      if (this._unloaded) return
      this.setData({ themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' }, () => {
        if (nextGroupKey !== undefined) this.openGroup(nextGroupKey)
      })
    }, THEME_SHEET_CLOSE_MS)
  },
  closeThemeSheet() {
    if (!this.data.themeSheetOpen || this.data.themeSheetClosing) return
    clearTimeout(this._themeSheetSelectTimer)
    this.setData({ themeSheetClosing: true, themeSheetPendingKey: '__idle__' }, () => this.finishThemeSheetClose())
  },
  searchThemes(event) {
    const themeQuery = String(event.detail.value || '')
    const themeSheetGroups = (Array.isArray(this.data.groupChips) ? this.data.groupChips : []).filter(group => themeSearchMatch(group, themeQuery))
    this.setData({ themeQuery, themeSheetGroups, themeSheetPendingKey: '__idle__' })
  },
  clearThemeSearch() {
    this.setData({ themeQuery: '', themeSheetPendingKey: '__idle__', themeSheetGroups: Array.isArray(this.data.groupChips) ? this.data.groupChips : [] })
  },
  chooseThemeFromSheet(event) {
    if (this.data.themeSheetClosing) return
    const key = String(event.currentTarget.dataset.key || '')
    clearTimeout(this._themeSheetSelectTimer)
    this.setData({ themeSheetPendingKey: key }, () => {
      this._themeSheetSelectTimer = setTimeout(() => {
        this._themeSheetSelectTimer = null
        if (this._unloaded || !this.data.themeSheetOpen) return
        this.setData({ themeSheetClosing: true }, () => this.finishThemeSheetClose(key))
      }, THEME_SHEET_SELECT_DELAY_MS)
    })
  },
  stopThemeSheetTap() {},
  preventBackgroundScroll() {},
  changeGraphPage(event) {
    const next = this.data.scene.page + Number(event.currentTarget.dataset.step)
    if (!Number.isFinite(next) || next < 0 || next >= this.data.scene.pageCount) return
    this._graphPage = next; this._selectedId = 0
    this.applyView(true)
  },
  onGraphNodeTap(event) {
    if (Date.now() < (this._suppressTapUntil || 0)) return
    const { kind, id, key } = event.currentTarget.dataset
    if (kind === 'core') this.showOverview()
    else if (kind === 'group') this.openGroup(String(key))
    else if (kind === 'point' && this._nodeById.has(Number(id))) {
      this._selectedId = Number(id)
      this.applyView(false)
    }
  },
  locatePoint(event) {
    const point = this._nodeById.get(Number(event.currentTarget.dataset.id))
    if (!point) return
    const group = (this._filteredGroups || []).find(item => item.key === point.groupKey)
    const index = group ? group.nodes.findIndex(item => Number(item.knowledge_point_id) === Number(point.knowledge_point_id)) : -1
    if (index < 0) return
    this._selectedId = Number(point.knowledge_point_id)
    this._graphPage = Math.floor(index / POINTS_PER_PAGE)
    this._indexLimit = Math.max(INITIAL_INDEX_LIMIT, index + 1)
    this.setData({ activeGroupKey: point.groupKey }, () => this.applyView(true))
    wx.pageScrollTo({ selector: '#atlas-shell', duration: 220 })
  },
  loadMore() { this._indexLimit = (this._indexLimit || INITIAL_INDEX_LIMIT) + INITIAL_INDEX_LIMIT; this.applyView(false) },
  openPoint(event) {
    const id = Number(event.currentTarget.dataset.id)
    if (!id) return
    wx.navigateTo({ url: `/subpackages/study/knowledge-detail/index?knowledge_point_id=${id}` })
  },
  practicePoint(event) {
    const item = this._nodeById && this._nodeById.get(Number(event.currentTarget.dataset.id))
    if (!item || !item.hasPractice) return
    const count = Math.min(10, Math.max(1, Math.floor(item.trainable_question_count)))
    wx.navigateTo({ url: `/subpackages/study/practice/practice?subject_id=${this.subjectId}&mode=random&count=${count}&knowledge_point_id=${item.knowledge_point_id}&allow_repeat=1&autostart=1&source=knowledge_map` })
  },
  retry() { return this.loadMap() },

  measureViewport(reset = false) {
    if (!wx.createSelectorQuery || !this.data.subject) return
    wx.createSelectorQuery().in(this).select('#atlas-viewport').boundingClientRect(rect => {
      if (!rect || !rect.width || this._unloaded) return
      const changed = Math.abs(rect.width - this._frame.width) > 1 || Math.abs(rect.height - this._frame.height) > 1
      this._frame = { left: rect.left, top: rect.top + (this._scrollTop || 0), width: rect.width, height: rect.height }
      if (reset || changed) this.resetView()
    }).exec()
  },
  cameraPayload(includeMetrics = true, extra = {}) {
    if (!this._frame || !this._camera) return extra
    const payload = { ...extra, stageStyle: cameraStyle(this._camera) }
    if (!includeMetrics) return payload
    const fit = fitCamera(this._frame)
    const limits = cameraLimits(this._frame)
    const ratio = this._camera.scale / fit.scale
    return {
      ...payload,
      zoomText: `${Math.round(ratio * 100)}%`,
      zoomOutDisabled: this._camera.scale <= limits.min + .005,
      zoomInDisabled: this._camera.scale >= limits.max - .005,
    }
  },
  setCamera(camera, throttle = false, includeMetrics = true, extra = {}) {
    this._camera = camera
    if (throttle && this._cameraTimer) return
    const publish = () => {
      this._cameraTimer = null
      if (this._unloaded || !this._frame || !this._camera) return
      this.setData(this.cameraPayload(includeMetrics, extra))
    }
    if (throttle) this._cameraTimer = setTimeout(publish, CAMERA_FRAME_MS)
    else { clearTimeout(this._cameraTimer); publish() }
  },
  resetView() {
    this.stopCameraInertia()
    if (this._frame) this.setCamera(fitCamera(this._frame), false, true, { graphInteracting: false })
  },
  zoomGraph(event) {
    if (!this._frame) return
    this.stopCameraInertia()
    const factor = Number(event.currentTarget.dataset.step) > 0 ? 1.25 : .8
    this.setCamera(zoomCamera(this._camera, factor, { x: this._frame.width / 2, y: this._frame.height / 2 }, this._frame))
  },
  touchPositions(event) {
    return (event.touches || []).map(touch => ({
      x: touch.clientX - this._frame.left,
      y: touch.clientY + (this._scrollTop || 0) - this._frame.top,
    }))
  },
  startGraphTouch(event) {
    if (!this._frame) return
    this.stopCameraInertia()
    const touches = this.touchPositions(event)
    if (!touches.length) return
    const now = Date.now()
    this._gesture = {
      touches, camera: { ...this._camera }, moved: touches.length > 1,
      lastPoint: touches[0], lastAt: now, velocityX: 0, velocityY: 0,
    }
    // 在首帧 move 之前关闭 CSS 过渡，避免舞台“追手”。
    if (!this.data.graphInteracting) this.setData({ graphInteracting: true })
  },
  moveGraphTouch(event) {
    if (!this._gesture) return
    const touches = this.touchPositions(event)
    if (!touches.length) return
    if (touches.length !== this._gesture.touches.length) { this.startGraphTouch(event); return }
    const start = this._gesture
    if (touches.length > 1) {
      const a = start.touches; const b = touches
      const distance = Math.hypot(a[1].x - a[0].x, a[1].y - a[0].y)
      if (distance < 1) return
      const anchor = { x: (a[0].x + a[1].x) / 2, y: (a[0].y + a[1].y) / 2 }
      const midpoint = { x: (b[0].x + b[1].x) / 2, y: (b[0].y + b[1].y) / 2 }
      const limits = cameraLimits(this._frame)
      const scale = Math.max(limits.min, Math.min(limits.max, start.camera.scale * Math.hypot(b[1].x - b[0].x, b[1].y - b[0].y) / distance))
      this.setCamera(clampCamera({ scale, x: midpoint.x - (anchor.x - start.camera.x) * scale / start.camera.scale, y: midpoint.y - (anchor.y - start.camera.y) * scale / start.camera.scale }, this._frame), true, false)
      start.moved = true
      start.velocityX = 0
      start.velocityY = 0
    } else {
      const dx = touches[0].x - start.touches[0].x
      const dy = touches[0].y - start.touches[0].y
      if (Math.abs(dx) + Math.abs(dy) > PAN_THRESHOLD) start.moved = true
      if (start.moved) {
        const now = Date.now()
        const elapsed = Math.max(8, Math.min(40, now - start.lastAt))
        const instantX = (touches[0].x - start.lastPoint.x) / elapsed
        const instantY = (touches[0].y - start.lastPoint.y) / elapsed
        start.velocityX = start.velocityX * .62 + instantX * .38
        start.velocityY = start.velocityY * .62 + instantY * .38
        start.lastPoint = touches[0]
        start.lastAt = now
        this.setCamera(clampCamera({ ...start.camera, x: start.camera.x + dx, y: start.camera.y + dy }, this._frame), true, false)
      }
    }
  },
  endGraphTouch(event) {
    const gesture = this._gesture
    if (gesture && gesture.moved) this._suppressTapUntil = Date.now() + 280
    this._gesture = null
    if (event && event.touches && event.touches.length) { this.startGraphTouch(event); return }
    const cancelled = event && event.type === 'touchcancel'
    if (!cancelled && gesture && gesture.moved && gesture.touches.length === 1) {
      const speed = Math.hypot(gesture.velocityX, gesture.velocityY)
      if (speed >= INERTIA_MIN_SPEED) {
        this.startCameraInertia(gesture.velocityX, gesture.velocityY)
        return
      }
    }
    this.finishGraphInteraction()
  },
  stopCameraInertia() {
    clearTimeout(this._inertiaTimer)
    this._inertiaTimer = null
  },
  finishGraphInteraction() {
    if (!this._camera || !this._frame) return
    this.setCamera(clampCamera(this._camera, this._frame), false, true, { graphInteracting: false })
  },
  startCameraInertia(velocityX, velocityY) {
    this.stopCameraInertia()
    let vx = velocityX
    let vy = velocityY
    let previous = Date.now()
    const step = () => {
      if (this._unloaded || this._gesture || !this._frame || !this._camera) return
      const now = Date.now()
      const elapsed = Math.max(8, Math.min(32, now - previous))
      previous = now
      const decay = Math.pow(INERTIA_DECAY, elapsed / CAMERA_FRAME_MS)
      vx *= decay
      vy *= decay
      const raw = { ...this._camera, x: this._camera.x + vx * elapsed, y: this._camera.y + vy * elapsed }
      const next = clampCamera(raw, this._frame)
      if (Math.abs(next.x - raw.x) > .01) vx = 0
      if (Math.abs(next.y - raw.y) > .01) vy = 0
      this.setCamera(next, true, false)
      if (Math.hypot(vx, vy) < INERTIA_MIN_SPEED) {
        this._inertiaTimer = null
        this.finishGraphInteraction()
        return
      }
      this._inertiaTimer = setTimeout(step, CAMERA_FRAME_MS)
    }
    this._inertiaTimer = setTimeout(step, CAMERA_FRAME_MS)
  },
})

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
const THEME_TRANSITION_MS = 180
const LABEL_SWITCH_OUT_MS = 72
const SELECTION_SWITCH_OUT_MS = 82
const SELECTION_SWITCH_IN_MS = 220
const RETURN_REFRESH_DELAY_MS = 260
const VIEW_STATE_VERSION = 2
const VIEW_STATE_MAX_AGE_MS = 30 * 60 * 1000
const CAMERA_FRAME_MS = 16
const PAN_THRESHOLD = 5
const INERTIA_MIN_SPEED = 0.025
const INERTIA_DECAY = 0.91
const SEARCH_SEPARATOR_RE = /[\s\-_/\\·•,，。.;；:：()（）[\]【】{}<>《》'"“”‘’]+/g
const nonnegative = value => Math.max(0, Number(value) || 0)
const normalizeSearchText = value => String(value || '').trim().toLowerCase()
const compactSearchText = value => normalizeSearchText(value).replace(SEARCH_SEPARATOR_RE, '')
const searchTokens = value => normalizeSearchText(value).split(SEARCH_SEPARATOR_RE).filter(Boolean)
const textSearchMatch = (value, rawQuery, compactQuery, tokens) => {
  const raw = normalizeSearchText(value)
  if (!raw) return false
  const compact = compactSearchText(raw)
  return raw.includes(rawQuery)
    || Boolean(compactQuery && compact.includes(compactQuery))
    || Boolean(tokens.length > 1 && tokens.every(token => raw.includes(token) || compact.includes(compactSearchText(token))))
}
const pointSearchMatch = (node, query) => {
  const rawQuery = normalizeSearchText(query)
  if (!rawQuery) return { matched: true, alias: '' }
  const compactQuery = compactSearchText(rawQuery)
  const tokens = searchTokens(rawQuery)
  if (textSearchMatch(node && node.name, rawQuery, compactQuery, tokens)) return { matched: true, alias: '' }
  const aliases = Array.isArray(node && node.aliases) ? node.aliases : []
  const alias = aliases.find(value => textSearchMatch(value, rawQuery, compactQuery, tokens)) || ''
  return { matched: Boolean(alias), alias: String(alias || '') }
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
const buildQuickGroupChips = (chips, activeKey, recentKeys = []) => {
  const source = Array.isArray(chips) ? chips : []
  const recentRank = new Map((Array.isArray(recentKeys) ? recentKeys : []).map((key, index) => [String(key), index]))
  const ranked = source.slice().sort((a, b) => {
    const aRecent = recentRank.has(String(a.key)) ? recentRank.get(String(a.key)) : Number.MAX_SAFE_INTEGER
    const bRecent = recentRank.has(String(b.key)) ? recentRank.get(String(b.key)) : Number.MAX_SAFE_INTEGER
    if (aRecent !== bRecent && (aRecent !== Number.MAX_SAFE_INTEGER || bRecent !== Number.MAX_SAFE_INTEGER)) return aRecent - bRecent
    const aStructured = Number(a.descendantCount) > 0 ? 1 : 0
    const bStructured = Number(b.descendantCount) > 0 ? 1 : 0
    if (aStructured !== bStructured) return bStructured - aStructured
    if (aStructured && Number(a.descendantCount) !== Number(b.descendantCount)) return Number(b.descendantCount) - Number(a.descendantCount)
    return Number(a.orderIndex || 0) - Number(b.orderIndex || 0)
  })
  const result = ranked.slice(0, QUICK_THEME_LIMIT)
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
    pageEntered: false, sceneAnimating: false, themeSwitching: false, themeSwitchPhase: '', selectionSwitching: false, selectionSwitchPhase: '', graphInteracting: false,
    stageStyle: '', zoomText: '100%', zoomInDisabled: false, zoomOutDisabled: true, selectedPoint: null,
    indexNodes: [], indexCount: 0, indexDisplayCount: 0, hasMore: false,
    practiceLaunching: false, practiceLaunchingId: 0,
  },

  onLoad(options) {
    this.subjectId = Number(options && options.subject_id)
    this._viewStateStorageKey = Number.isInteger(this.subjectId) && this.subjectId > 0
      ? `knowledgeSubjectViewState:${this.subjectId}`
      : ''
    this._pendingReturnState = null
    this._returnRefreshTimer = null
    this._practiceLaunchFeedbackTimer = null
    this._practiceNavigationPending = false
    this._detailNavigationPending = false
    this._focusNodeId = 0
    this._expandedNodeIds = new Set()
    let width = 375
    try {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
      width = Number(info.windowWidth) || width
    } catch (error) { /* 使用默认宽度，布局挂载后按实际容器尺寸校准。 */ }
    this._frame = { left: 0, top: 0, width: width * 702 / 750, height: width * 860 / 750 }
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

    const persistedState = String((options && options.restore_state) || '') === '1'
      ? this._readViewState(true)
      : null
    if (persistedState) this._primeViewState(persistedState)
    return this.loadMap(true, { preserveViewState: persistedState })
  },

  onReady() { this.measureViewport(!this._pendingInitialViewState) },
  onShow() {
    this._practiceNavigationPending = false
    this._detailNavigationPending = false
    if (this._practiceLaunchFeedbackTimer) {
      clearTimeout(this._practiceLaunchFeedbackTimer)
      this._practiceLaunchFeedbackTimer = null
    }
    if (!this._loadedOnce) return

    const restoreState = this._pendingReturnState || this._captureViewState()
    this._pendingReturnState = null
    if (this.data.practiceLaunching || this.data.practiceLaunchingId) {
      this.setData({ practiceLaunching: false, practiceLaunchingId: 0 })
    }
    this._restoreScrollPosition(restoreState)

    clearTimeout(this._returnRefreshTimer)
    this._returnRefreshTimer = setTimeout(() => {
      this._returnRefreshTimer = null
      if (!this._unloaded) this.loadMap(false, { preserveViewState: restoreState })
    }, RETURN_REFRESH_DELAY_MS)
  },
  onPageScroll(event) { this._scrollTop = Number(event.scrollTop) || 0 },
  onHide() { clearTimeout(this._returnRefreshTimer) },
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
    clearTimeout(this._selectionSwitchTimer)
    clearTimeout(this._selectionSettleTimer)
    clearTimeout(this._returnRefreshTimer)
    clearTimeout(this._practiceLaunchFeedbackTimer)
    this._practiceLaunchFeedbackTimer = null
    this._practiceNavigationPending = false
    this._detailNavigationPending = false
  },
  onPullDownRefresh() { return this.loadMap(false, { preserveViewState: this._captureViewState() }).finally(() => wx.stopPullDownRefresh()) },

  _captureViewState() {
    if (!Number.isInteger(this.subjectId) || this.subjectId <= 0) return null
    const camera = this._camera && Number.isFinite(Number(this._camera.scale))
      ? { x: Number(this._camera.x) || 0, y: Number(this._camera.y) || 0, scale: Number(this._camera.scale) || 1 }
      : null
    return {
      version: VIEW_STATE_VERSION,
      subjectId: this.subjectId,
      savedAt: Date.now(),
      filter: String(this.data.filter || 'all'),
      query: String(this.data.query || ''),
      activeGroupKey: String(this.data.activeGroupKey || ''),
      focusNodeId: Math.max(0, Number(this._focusNodeId) || 0),
      graphPage: Math.max(0, Number(this._graphPage) || 0),
      selectedId: Math.max(0, Number(this._selectedId) || Number(this.data.selectedPoint && this.data.selectedPoint.knowledge_point_id) || 0),
      expandedNodeIds: Array.from(this._expandedNodeIds || []).map(Number).filter(id => Number.isInteger(id) && id > 0).slice(0, 160),
      indexLimit: Math.max(INITIAL_INDEX_LIMIT, Number(this._indexLimit) || INITIAL_INDEX_LIMIT),
      scrollTop: Math.max(0, Number(this._scrollTop) || 0),
      camera,
    }
  },

  _persistViewState(state) {
    const snapshot = state || this._captureViewState()
    if (!snapshot || !this._viewStateStorageKey) return
    try { wx.setStorageSync(this._viewStateStorageKey, snapshot) } catch (error) { /* 存储空间不足时仅放弃跨页面栈恢复。 */ }
  },

  _readViewState(consume = false) {
    if (!this._viewStateStorageKey) return null
    try {
      const state = wx.getStorageSync(this._viewStateStorageKey)
      if (consume) wx.removeStorageSync(this._viewStateStorageKey)
      if (!state || Number(state.version) !== VIEW_STATE_VERSION || Number(state.subjectId) !== this.subjectId) return null
      if (Date.now() - Number(state.savedAt || 0) > VIEW_STATE_MAX_AGE_MS) return null
      return state
    } catch (error) {
      return null
    }
  },

  _viewStateDataPatch(state) {
    if (!state) return {}
    const filter = FILTERS.some(item => item.id === state.filter) ? state.filter : 'all'
    return {
      filter,
      query: String(state.query || '').slice(0, 80),
      activeGroupKey: String(state.activeGroupKey || ''),
      searchPending: false,
      searchFocused: false,
      themeSheetOpen: false,
      themeSheetClosing: false,
      themeSheetPendingKey: '__idle__',
      themeQuery: '',
    }
  },

  _primeViewState(state) {
    if (!state) return
    this._pendingInitialViewState = state
    this._focusNodeId = Math.max(0, Number(state.focusNodeId) || 0)
    this._graphPage = Math.max(0, Number(state.graphPage) || 0)
    this._selectedId = Math.max(0, Number(state.selectedId) || 0)
    this._expandedNodeIds = new Set((Array.isArray(state.expandedNodeIds) ? state.expandedNodeIds : []).map(Number).filter(id => Number.isInteger(id) && id > 0))
    this._indexLimit = Math.max(INITIAL_INDEX_LIMIT, Number(state.indexLimit) || INITIAL_INDEX_LIMIT)
    this._scrollTop = Math.max(0, Number(state.scrollTop) || 0)
    if (state.camera && this._frame) {
      const candidate = { x: Number(state.camera.x) || 0, y: Number(state.camera.y) || 0, scale: Number(state.camera.scale) || 1 }
      this._camera = clampCamera(candidate, this._frame)
    }
    this.setData({ ...this._viewStateDataPatch(state), ...this.cameraPayload(true) })
  },

  _restoreScrollPosition(state) {
    const scrollTop = state ? Math.max(0, Number(state.scrollTop) || 0) : 0
    if (!scrollTop || typeof wx.pageScrollTo !== 'function') return
    const restore = () => wx.pageScrollTo({ scrollTop, duration: 0 })
    if (typeof wx.nextTick === 'function') wx.nextTick(restore)
    else setTimeout(restore, 0)
  },

  async loadMap(showLoading = true, options = {}) {
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
      this._groups.forEach(group => group.nodes.forEach((node) => {
        const pathNames = (Array.isArray(node.pathIds) ? node.pathIds : [])
          .map(id => group.nodes.find(item => Number(item.knowledge_point_id) === Number(id)))
          .filter(Boolean)
          .map(item => item.name)
        this._nodeById.set(Number(node.knowledge_point_id), {
          ...node,
          groupKey: group.key,
          groupName: group.name,
          pathText: pathNames.join(' > ') || group.name,
        })
      }))
      const validNodeIds = new Set(this._nodeById.keys())
      this._expandedNodeIds = new Set(Array.from(this._expandedNodeIds || []).filter(id => validNodeIds.has(Number(id))))
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
      const preserveViewState = options && options.preserveViewState
      if (preserveViewState) {
        this._focusNodeId = Math.max(0, Number(preserveViewState.focusNodeId) || 0)
        this._graphPage = Math.max(0, Number(preserveViewState.graphPage) || 0)
        this._selectedId = Math.max(0, Number(preserveViewState.selectedId) || 0)
        this._expandedNodeIds = new Set((Array.isArray(preserveViewState.expandedNodeIds) ? preserveViewState.expandedNodeIds : [])
          .map(Number)
          .filter(id => Number.isInteger(id) && id > 0 && validNodeIds.has(id)))
        this._indexLimit = Math.max(INITIAL_INDEX_LIMIT, Number(preserveViewState.indexLimit) || INITIAL_INDEX_LIMIT)
        if (preserveViewState.camera && this._frame) {
          this._camera = clampCamera({
            x: Number(preserveViewState.camera.x) || 0,
            y: Number(preserveViewState.camera.y) || 0,
            scale: Number(preserveViewState.camera.scale) || 1,
          }, this._frame)
        }
      }
      this._loadedOnce = true
      wx.setNavigationBarTitle({ title: `${data.subject.subject_name} · 知识图谱` })
      this.setData({
        loading: false, error: '', refreshError: '', subject: data.subject, filters,
        syllabusText: syllabus ? [syllabus.name, syllabus.effective_year].filter(Boolean).join(' · ') : '',
        stats: { total, reliable, weak, coverage: coverage == null ? 0 : coverage },
        ...(preserveViewState ? this._viewStateDataPatch(preserveViewState) : {}),
        ...(preserveViewState ? this.cameraPayload(true) : {}),
      }, () => this.applyView(firstLoad && !preserveViewState, firstLoad && !preserveViewState, () => {
        if (firstLoad) this.enterPage()
        if (preserveViewState) this._restoreScrollPosition(preserveViewState)
        this._pendingInitialViewState = null
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
    const forceOpenTree = Boolean(query) || config.id !== 'all'

    this._filteredGroups = (this._groups || []).map((group, groupIndex) => {
      const groupIconKind = themeIconKind(group, groupIndex)
      const groupIconSrc = themeIconSrc(groupIconKind)
      const fullById = new Map(group.nodes.map(node => [Number(node.knowledge_point_id), node]))
      const matchedIds = new Set()
      const matchedAliases = new Map()

      group.nodes.forEach((node) => {
        if (config.statuses && !config.statuses.includes(node.status)) return
        const searchMatch = pointSearchMatch(node, query)
        if (!searchMatch.matched) return
        const id = Number(node.knowledge_point_id)
        matchedIds.add(id)
        if (searchMatch.alias) matchedAliases.set(id, searchMatch.alias)
      })

      const visibleIds = new Set(matchedIds)
      if (forceOpenTree) {
        matchedIds.forEach((id) => {
          let cursor = fullById.get(Number(id))
          const seen = new Set()
          while (cursor && cursor.parentId && !seen.has(Number(cursor.parentId))) {
            const parentId = Number(cursor.parentId)
            seen.add(parentId)
            if (!fullById.has(parentId)) break
            visibleIds.add(parentId)
            cursor = fullById.get(parentId)
          }
        })
      }

      let filteredNodes = group.nodes.reduce((result, node, nodeIndex) => {
        const id = Number(node.knowledge_point_id)
        if (!visibleIds.has(id)) return result
        const nodeIconKind = themeIconKind({ name: node.name, key: node.knowledge_point_id }, nodeIndex)
        result.push({
          ...node,
          groupKey: String(group.key),
          groupName: group.name,
          iconKind: nodeIconKind,
          iconSrc: themeIconSrc(nodeIconKind),
          matched: matchedIds.has(id),
          contextOnly: !matchedIds.has(id),
          matchedAlias: matchedAliases.get(id) || '',
        })
        return result
      }, [])

      const visibleChildCount = new Map()
      filteredNodes.forEach((node) => {
        const parentId = Number(node.parentId)
        if (!parentId) return
        visibleChildCount.set(parentId, (visibleChildCount.get(parentId) || 0) + 1)
      })
      filteredNodes = filteredNodes.map(node => ({ ...node, visibleChildCount: visibleChildCount.get(Number(node.knowledge_point_id)) || 0 }))

      return {
        ...group,
        iconKind: groupIconKind,
        iconSrc: groupIconSrc,
        matchCount: matchedIds.size,
        nodes: filteredNodes,
        rootNode: filteredNodes.find(node => Number(node.knowledge_point_id) === Number(group.rootId)) || null,
      }
    })

    const availableGroups = this._filteredGroups.filter(group => group.matchCount > 0 && group.nodes.length)
    let activeGroupKey = availableGroups.some(group => String(group.key) === String(this.data.activeGroupKey)) ? String(this.data.activeGroupKey) : ''
    let activeFilteredGroup = activeGroupKey ? availableGroups.find(group => String(group.key) === activeGroupKey) : null
    let focusNodeId = 0
    if (activeFilteredGroup) {
      focusNodeId = Number(this._focusNodeId) || Number(activeFilteredGroup.rootId) || 0
      if (!activeFilteredGroup.nodes.some(node => Number(node.knowledge_point_id) === focusNodeId)) {
        focusNodeId = Number(activeFilteredGroup.rootId) || 0
      }
      const focusBase = this._nodeById && this._nodeById.get(focusNodeId)
      ;(focusBase && Array.isArray(focusBase.pathIds) ? focusBase.pathIds : []).forEach(id => this._expandedNodeIds.add(Number(id)))
    } else {
      activeGroupKey = ''
      this._focusNodeId = 0
    }
    this._focusNodeId = focusNodeId

    const scopedGroups = activeFilteredGroup ? [activeFilteredGroup] : availableGroups
    this._visibleNodes = scopedGroups.reduce((result, group) => result.concat(group.nodes), [])

    let scene = buildScene(availableGroups, this.data.subject, {
      groupKey: activeGroupKey,
      focusNodeId,
      page: this._graphPage || 0,
      selectedId: this._selectedId,
    })
    this._focusNodeId = Number(scene.focusNodeId) || 0

    if (!scene.pointIds.some(id => Number(id) === Number(this._selectedId))) {
      this._selectedId = scene.focused && scene.pointIds.length ? Number(scene.pointIds[0]) : 0
      scene = buildScene(availableGroups, this.data.subject, {
        groupKey: activeGroupKey,
        focusNodeId: this._focusNodeId,
        page: scene.page,
        selectedId: this._selectedId,
      })
    }
    this._graphPage = scene.page

    const limit = this._indexLimit || INITIAL_INDEX_LIMIT
    const indexRows = []
    scopedGroups.forEach((group) => {
      const byParent = new Map()
      group.nodes.forEach((node) => {
        const parentId = Number(node.parentId) || 0
        if (!byParent.has(parentId)) byParent.set(parentId, [])
        byParent.get(parentId).push(node)
      })
      const root = group.nodes.find(node => Number(node.knowledge_point_id) === Number(group.rootId))
      if (!root) return
      const walk = (node) => {
        const id = Number(node.knowledge_point_id)
        const children = byParent.get(id) || []
        const indexExpandable = children.length > 0
        const indexForcedOpen = indexExpandable && forceOpenTree
        const indexExpanded = indexExpandable && (indexForcedOpen || this._expandedNodeIds.has(id))
        let indexMetaText = `${node.statusText} · ${node.trainable_question_count} 题可练`
        if (node.contextOnly) indexMetaText = `路径 · ${children.length || node.visibleChildCount || 1} 个匹配分支`
        else if (node.hasChildren) indexMetaText = `${node.childCount} 个子节点 · ${node.descendantCount} 个下级知识点`
        const indexActionText = indexForcedOpen
          ? (node.contextOnly ? '路径' : '查看')
          : (indexExpandable ? (indexExpanded ? '收起' : '展开') : (node.hasChildren ? '父级' : '定位'))
        indexRows.push({
          ...node,
          indexExpandable,
          indexForcedOpen,
          indexExpanded,
          indexMetaText,
          indexActionText,
          indexAriaAction: indexForcedOpen ? '在图谱中查看' : (indexExpandable ? (indexExpanded ? '收起' : '展开') : (node.hasChildren ? '父级路径' : '在图谱中定位')),
        })
        if (indexExpanded) children.forEach(walk)
      }
      walk(root)
    })

    const visibleById = new Map(this._visibleNodes.map(node => [Number(node.knowledge_point_id), node]))
    const selectedVisible = visibleById.get(Number(this._selectedId)) || null
    const selectedBase = this._nodeById && this._nodeById.get(Number(this._selectedId))
    const filteredByKey = new Map((this._filteredGroups || []).map(group => [String(group.key), group]))
    const groupChips = (this._groups || []).map((group, index) => {
      const filteredGroup = filteredByKey.get(String(group.key))
      const iconKind = themeIconKind(group, index)
      return {
        key: String(group.key),
        name: group.name,
        count: filteredGroup ? filteredGroup.matchCount : 0,
        number: group.number,
        orderText: formatThemeOrder(group, index),
        iconKind,
        iconSrc: themeIconSrc(iconKind),
        nodeCount: Number(group.nodeCount || group.nodes.length || 0),
        descendantCount: Number(group.descendantCount || 0),
        directChildCount: Number(group.directChildCount || 0),
        orderIndex: index,
      }
    })
    const quickGroupChips = buildQuickGroupChips(groupChips, activeGroupKey, this._recentGroupKeys)
    const themeSheetGroups = groupChips.filter(group => themeSearchMatch(group, this.data.themeQuery))
    const activeGroup = groupChips.find(group => group.key === activeGroupKey)
    const indexCount = scopedGroups.reduce((count, group) => count + Number(group.matchCount || 0), 0)
    const searchResultCount = availableGroups.reduce((count, group) => count + Number(group.matchCount || 0), 0)
    const payload = {
      activeGroupKey,
      activeGroupName: activeGroup ? activeGroup.name : '',
      scene,
      groupChips,
      quickGroupChips,
      themeGroupCount: groupChips.length,
      themeSheetGroups,
      searchPending: false,
      searchResultCount,
      selectedPoint: selectedBase && selectedVisible ? { ...selectedBase, matchedAlias: selectedVisible.matchedAlias || '' } : null,
      indexNodes: indexRows.slice(0, limit),
      indexCount,
      indexDisplayCount: indexRows.length,
      hasMore: indexRows.length > limit,
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
    clearTimeout(this._selectionSwitchTimer)
    clearTimeout(this._selectionSettleTimer)
    const startPayload = { ...dataChanges, sceneAnimating: false, themeSwitching: true, themeSwitchPhase: 'leaving', selectionSwitching: false, selectionSwitchPhase: '' }
    this.setData(startPayload, () => {
      this._labelSwitchTimer = setTimeout(() => {
        this._labelSwitchTimer = null
        if (this._unloaded) return
        // 主题切换时保留当前相机视角，避免节点重建与相机复位同时发生造成抖动。
        // 内容本身只做轻量淡入淡出，不再对单个节点做位移/缩放动画。
        this.applyView(false, false, () => {
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
    const targetGroup = normalized
      ? (this._filteredGroups || []).find(group => String(group.key) === normalized && group.matchCount > 0 && group.nodes.length)
      : null
    if (normalized && !targetGroup) return
    if (targetGroup && targetGroup.rootNode && !targetGroup.rootNode.hasChildren) {
      this.locatePointById(Number(targetGroup.rootId))
      return
    }
    const targetFocusId = targetGroup ? Number(targetGroup.rootId) || 0 : 0
    if (normalized === this.data.activeGroupKey && Number(this._focusNodeId) === targetFocusId) return
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    this._focusNodeId = targetFocusId
    if (targetFocusId) this._expandedNodeIds.add(targetFocusId)
    if (normalized) this.rememberGroup(normalized)
    const quickGroupChips = buildQuickGroupChips(this.data.groupChips, normalized, this._recentGroupKeys)
    this.transitionLabelView({ activeGroupKey: normalized, quickGroupChips })
  },
  showOverview() {
    this._focusNodeId = 0
    this.openGroup('')
  },
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
  navigateToFocus(groupKey, focusNodeId) {
    const normalizedGroupKey = String(groupKey || '')
    const nextFocusId = Math.max(0, Number(focusNodeId) || 0)
    if (!normalizedGroupKey || !nextFocusId) {
      this._focusNodeId = 0
      this.openGroup('')
      return
    }
    const group = (this._filteredGroups || []).find(item => String(item.key) === normalizedGroupKey && item.matchCount > 0)
    const node = group && group.nodes.find(item => Number(item.knowledge_point_id) === nextFocusId)
    if (!group || !node) return
    if (String(this.data.activeGroupKey) === normalizedGroupKey && Number(this._focusNodeId) === nextFocusId) return
    this._graphPage = 0
    this._selectedId = 0
    this._focusNodeId = nextFocusId
    const base = this._nodeById && this._nodeById.get(nextFocusId)
    ;(base && Array.isArray(base.pathIds) ? base.pathIds : [nextFocusId]).forEach(id => this._expandedNodeIds.add(Number(id)))
    const quickGroupChips = buildQuickGroupChips(this.data.groupChips, normalizedGroupKey, this._recentGroupKeys)
    this.transitionLabelView({ activeGroupKey: normalizedGroupKey, quickGroupChips })
  },
  onGraphBreadcrumbTap(event) {
    const focusNodeId = Number(event.currentTarget.dataset.id) || 0
    const groupKey = String(event.currentTarget.dataset.key || '')
    if (!focusNodeId) this.showOverview()
    else this.navigateToFocus(groupKey, focusNodeId)
  },
  onGraphNodeTap(event) {
    if (Date.now() < (this._suppressTapUntil || 0)) return
    const { kind, id, key } = event.currentTarget.dataset
    if (kind === 'core') {
      if (!this.data.scene.focused) return
      const parentFocusId = Number(this.data.scene.parentFocusId) || 0
      if (parentFocusId) this.navigateToFocus(String(this.data.scene.groupKey || key || ''), parentFocusId)
      else this.showOverview()
    } else if (kind === 'group') {
      this.navigateToFocus(String(key || ''), Number(id))
    } else if (kind === 'point' && this._nodeById.has(Number(id))) {
      this.selectGraphPoint(Number(id))
    }
  },
  selectGraphPoint(id) {
    const nextId = Number(id)
    if (!nextId || !this._nodeById || !this._nodeById.has(nextId) || nextId === Number(this._selectedId)) return
    clearTimeout(this._selectionSwitchTimer)
    clearTimeout(this._selectionSettleTimer)

    const commitSelection = () => {
      if (this._unloaded) return
      this._selectedId = nextId
      this.applyView(false, false, () => {
        if (this._unloaded) return
        this.setData({ selectionSwitching: true, selectionSwitchPhase: 'entering' }, () => {
          this._selectionSettleTimer = setTimeout(() => {
            this._selectionSettleTimer = null
            if (!this._unloaded) this.setData({ selectionSwitching: false, selectionSwitchPhase: '' })
          }, SELECTION_SWITCH_IN_MS)
        })
      })
    }

    if (!this.data.selectedPoint) {
      this.setData({ selectionSwitching: true, selectionSwitchPhase: 'entering' }, commitSelection)
      return
    }

    this.setData({ selectionSwitching: true, selectionSwitchPhase: 'leaving' }, () => {
      this._selectionSwitchTimer = setTimeout(() => {
        this._selectionSwitchTimer = null
        commitSelection()
      }, SELECTION_SWITCH_OUT_MS)
    })
  },
  handleIndexRowTap(event) {
    const id = Number(event.currentTarget.dataset.id)
    const node = this._nodeById && this._nodeById.get(id)
    if (!node) return
    const group = (this._filteredGroups || []).find(item => String(item.key) === String(node.groupKey))
    const filteredNode = group && group.nodes.find(item => Number(item.knowledge_point_id) === id)
    const visibleChildren = group ? group.nodes.filter(item => Number(item.parentId) === id) : []
    if (visibleChildren.length) {
      const forceOpenTree = Boolean(normalizeSearchText(this.data.query)) || this.data.filter !== 'all'
      if (forceOpenTree) {
        this.navigateToFocus(String(node.groupKey), id)
        return
      }
      if (this._expandedNodeIds.has(id)) this._expandedNodeIds.delete(id)
      else this._expandedNodeIds.add(id)
      this._indexLimit = Math.max(INITIAL_INDEX_LIMIT, Number(this._indexLimit) || INITIAL_INDEX_LIMIT)
      this.applyView(false, false)
      return
    }
    // 搜索/状态筛选下，父节点可能保留为上下文但子项被过滤掉；此时不把父节点伪装成叶子节点。
    if ((filteredNode && filteredNode.hasChildren) || node.hasChildren) return
    this.locatePointById(id)
  },
  locatePoint(event) { this.locatePointById(Number(event.currentTarget.dataset.id)) },
  locatePointById(id) {
    const point = this._nodeById && this._nodeById.get(Number(id))
    if (!point) return
    const group = (this._filteredGroups || []).find(item => String(item.key) === String(point.groupKey))
    if (!group) return

    this._selectedId = Number(point.knowledge_point_id)
    this._indexLimit = Math.max(INITIAL_INDEX_LIMIT, Number(this._indexLimit) || INITIAL_INDEX_LIMIT)
    ;(Array.isArray(point.pathIds) ? point.pathIds : []).forEach(pathId => this._expandedNodeIds.add(Number(pathId)))

    const parentId = Number(point.parentId) || 0
    if (parentId) {
      const siblings = group.nodes.filter(item => Number(item.parentId) === parentId)
      const index = siblings.findIndex(item => Number(item.knowledge_point_id) === Number(point.knowledge_point_id))
      if (index < 0) return
      this._focusNodeId = parentId
      this._graphPage = Math.floor(index / POINTS_PER_PAGE)
      this.setData({ activeGroupKey: String(point.groupKey) }, () => this.applyView(true))
    } else {
      const availableGroups = (this._filteredGroups || []).filter(item => item.matchCount > 0 && item.nodes.length)
      const groupIndex = availableGroups.findIndex(item => String(item.key) === String(point.groupKey))
      if (groupIndex < 0) return
      this._focusNodeId = 0
      this._graphPage = Math.floor(groupIndex / POINTS_PER_PAGE)
      this.setData({ activeGroupKey: '' }, () => this.applyView(true))
    }
    wx.pageScrollTo({ selector: '#atlas-shell', duration: 220 })
  },

  loadMore() { this._indexLimit = (this._indexLimit || INITIAL_INDEX_LIMIT) + INITIAL_INDEX_LIMIT; this.applyView(false) },
  openPoint(event) {
    const id = Number(event.currentTarget.dataset.id)
    if (!id || this._detailNavigationPending || this._practiceNavigationPending) return

    const state = this._captureViewState()
    this._pendingReturnState = state
    this._persistViewState(state)

    // 详情入口使用实例锁而不是 setData 锁：既能阻止快速连点叠出两个
    // knowledge-detail 页面，又不会为了禁用按钮先重绘一次当前卡片。
    this._detailNavigationPending = true
    wx.navigateTo({
      url: `/subpackages/study/knowledge-detail/index?knowledge_point_id=${id}`,
      fail: () => {
        this._detailNavigationPending = false
        if (!this._unloaded) wx.showToast({ title: '知识详情打开失败，请重试', icon: 'none' })
      },
    })
  },
  practicePoint(event) {
    const item = this._nodeById && this._nodeById.get(Number(event.currentTarget.dataset.id))
    if (!item || !item.hasPractice || this._practiceNavigationPending || this.data.practiceLaunching) return

    const state = this._captureViewState()
    this._pendingReturnState = state
    this._persistViewState(state)

    const count = Math.min(10, Math.max(1, Math.floor(item.trainable_question_count)))
    const returnTo = encodeURIComponent(`/subpackages/study/knowledge-subject/index?subject_id=${this.subjectId}&restore_state=1`)
    const subjectName = encodeURIComponent(String((this.data.subject && this.data.subject.subject_name) || item.groupName || '专项练习'))
    const url = `/subpackages/study/practice/practice?subject_id=${this.subjectId}&subject_name=${subjectName}&mode=random&count=${count}&knowledge_point_id=${item.knowledge_point_id}&include_children=1&allow_repeat=1&autostart=1&source=knowledge_map&return_to=${returnTo}`

    // 快速导航时不抢先重绘当前知识点卡片，避免源页按钮先闪一下再进入练习。
    // 实例锁即时生效；只有导航超过阈值时才显示“正在进入”反馈。
    this._practiceNavigationPending = true
    if (this._practiceLaunchFeedbackTimer) clearTimeout(this._practiceLaunchFeedbackTimer)
    this._practiceLaunchFeedbackTimer = setTimeout(() => {
      this._practiceLaunchFeedbackTimer = null
      if (!this._unloaded && this._practiceNavigationPending) {
        this.setData({ practiceLaunching: true, practiceLaunchingId: Number(item.knowledge_point_id) })
      }
    }, 140)

    wx.navigateTo({
      url,
      success: () => {
        if (this._practiceLaunchFeedbackTimer) {
          clearTimeout(this._practiceLaunchFeedbackTimer)
          this._practiceLaunchFeedbackTimer = null
        }
      },
      fail: () => {
        if (this._practiceLaunchFeedbackTimer) {
          clearTimeout(this._practiceLaunchFeedbackTimer)
          this._practiceLaunchFeedbackTimer = null
        }
        this._practiceNavigationPending = false
        if (!this._unloaded && (this.data.practiceLaunching || this.data.practiceLaunchingId)) {
          this.setData({ practiceLaunching: false, practiceLaunchingId: 0 })
        }
        wx.showToast({ title: '练习页打开失败，请重试', icon: 'none' })
      },
    })
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

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
const INDEX_TREE_BASE_X = 42
const INDEX_TREE_STEP_X = 44
const INDEX_CONTENT_BASE_INDENT = 44
const QUICK_THEME_LIMIT = 5
const RECENT_THEME_LIMIT = 5
const SEARCH_DEBOUNCE_MS = 300
const INDEX_SEARCH_LEAVE_MS = 72
const INDEX_SEARCH_ENTER_MS = 210
const INDEX_SEARCH_HEIGHT_MS = 220
const INDEX_NAVIGATE_FEEDBACK_MS = 76
const INDEX_GRAPH_SCROLL_MS = 320
const INDEX_SEARCH_FLOOR_EPSILON = 1
const THEME_SHEET_SELECT_DELAY_MS = 96
const THEME_SHEET_CLOSE_MS = 236
const THEME_TRANSITION_MS = 180
const LABEL_SWITCH_OUT_MS = 72
const SELECTION_SWITCH_OUT_MS = 82
const SELECTION_SWITCH_IN_MS = 220
const RETURN_REFRESH_DELAY_MS = 260
const INDEX_ANCHOR_EPSILON = 1.25
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

const INDEX_ICON_ASSETS = {
  index: '/assets/icons/knowledge-index/index.svg',
  search: '/assets/icons/knowledge-index/search.svg',
  locate: '/assets/icons/knowledge-index/locate.svg',
  database: '/assets/icons/knowledge-index/database.svg',
  network: '/assets/icons/knowledge-index/network.svg',
  link: '/assets/icons/knowledge-index/link.svg',
  code: '/assets/icons/knowledge-index/code.svg',
  list: '/assets/icons/knowledge-index/list.svg',
  layers: '/assets/icons/knowledge-index/layers.svg',
  queue: '/assets/icons/knowledge-index/queue.svg',
  type: '/assets/icons/knowledge-index/type.svg',
  grid: '/assets/icons/knowledge-index/grid.svg',
  binary: '/assets/icons/knowledge-index/binary.svg',
  memory: '/assets/icons/knowledge-index/memory.svg',
  tree: '/assets/icons/knowledge-index/tree.svg',
  workflow: '/assets/icons/knowledge-index/workflow.svg',
}
const indexIconSrc = kind => INDEX_ICON_ASSETS[kind] || INDEX_ICON_ASSETS.link
const indexIconKind = (node, depth = 0, index = 0) => {
  const name = String(node && node.name ? node.name : '').toLowerCase()
  const text = `${name} ${node && node.groupName ? node.groupName : ''}`.toLowerCase()
  if (/存储|数据库|database|磁盘|文件|外存/.test(text)) return 'database'
  if (/逻辑|关系|图|网络|拓扑|graph|network/.test(text)) return 'network'
  if (/树|二叉|avl|b树|b-tree|tree/.test(text)) return 'tree'
  if (/队列|queue/.test(text)) return 'queue'
  if (/栈|stack|层|递归/.test(text)) return 'layers'
  if (/串|字符串|string|字符/.test(text)) return 'type'
  if (/数组|矩阵|matrix|array/.test(text)) return 'grid'
  if (/内存|cache|缓存|地址|页|memory/.test(text)) return 'memory'
  if (/二进制|binary|位运算|bit/.test(text)) return 'binary'
  if (/算法|代码|程序|排序|查找|search|sort|code|语言/.test(text)) return 'code'
  if (/线性结构.*非线性|结构关系|连接关系/.test(name)) return 'link'
  if (/^线性结构$|线性表|链表|顺序表|list|sequence/.test(name)) return 'list'
  if (/流程|步骤|过程|workflow/.test(text)) return 'workflow'
  if (depth >= 2) return 'link'
  return depth === 0
    ? ['database', 'network', 'code', 'list', 'tree', 'queue', 'type', 'grid'][index % 8]
    : ['network', 'list', 'tree', 'code'][index % 4]
}
const branchStatusText = node => node && node.tone === 'weak' ? '需强化' : (node && node.tone === 'stable' ? '较稳定' : '待建立')
const isEstablishedNode = node => Boolean(node && node.status && node.status !== 'no_data' && node.status !== 'insufficient')

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
const buildFilteredKnowledgeGroups = (groups, config, queryValue) => {
  const query = normalizeSearchText(queryValue)
  const forceOpenTree = Boolean(query) || config.id !== 'all'
  return (Array.isArray(groups) ? groups : []).map((group, groupIndex) => {
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
    filter: 'all', query: '', searchDraft: '', searchFocused: false, searchPending: false, searchResultCount: 0, activeGroupKey: '', activeGroupName: '',
    groupChips: [], quickGroupChips: [], themeGroupCount: 0, themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '', themeSheetGroups: [],
    scene: { nodes: [], edges: [], page: 0, pageCount: 1, focused: false },
    pageEntered: false, sceneAnimating: false, themeSwitching: false, themeSwitchPhase: '', selectionSwitching: false, selectionSwitchPhase: '', graphInteracting: false,
    stageStyle: '', zoomText: '100%', zoomInDisabled: false, zoomOutDisabled: true, selectedPoint: null,
    indexNodes: [], indexCount: 0, indexDisplayCount: 0, hasMore: false, indexSearchOpen: false, indexSearchFocused: false,
    indexQuery: '', indexSearchDraft: '', indexSearchPending: false, indexSearchResultCount: 0, indexNavigatingId: 0,
    indexResultsTransitioning: false, indexResultsPhase: '', indexResultsHeightStyle: '', indexResultsFloorStyle: '', indexResultsLayoutLocked: false,
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
    // Dedicated index search keeps a monotonic result-surface floor for the whole
    // search session. This prevents the document height from collapsing when a
    // long tree becomes a short/no-result state, which would otherwise clamp the
    // page scroll position upward into the graph section.
    this._indexSearchFloorHeight = 0
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
    clearTimeout(this._indexSearchTimer)
    clearTimeout(this._indexNavigateTimer)
    clearTimeout(this._indexSearchLeaveTimer)
    clearTimeout(this._indexSearchSettleTimer)
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
      searchDraft: String(state.query || '').slice(0, 80),
      activeGroupKey: String(state.activeGroupKey || ''),
      searchPending: false,
      searchFocused: false,
      indexSearchOpen: false,
      indexSearchFocused: false,
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
      if (!this._loadedOnce && !(options && options.preserveViewState) && !(this._expandedNodeIds && this._expandedNodeIds.size)) {
        const firstStructuredGroup = this._groups.find(group => group && group.rootNode && group.rootNode.hasChildren)
        if (firstStructuredGroup) {
          const rootId = Number(firstStructuredGroup.rootId)
          if (rootId) this._expandedNodeIds.add(rootId)
          const firstStructuredChild = firstStructuredGroup.nodes.find(node => Number(node.parentId) === rootId && node.hasChildren)
          if (firstStructuredChild) this._expandedNodeIds.add(Number(firstStructuredChild.knowledge_point_id))
        }
      }
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

  _buildIndexPayload(options = {}) {
    const config = FILTERS.find(item => item.id === this.data.filter) || FILTERS[0]
    const query = normalizeSearchText(options.query != null ? options.query : (this.data.indexQuery || this.data.query))
    const dedicatedQuery = normalizeSearchText(options.dedicatedQuery != null ? options.dedicatedQuery : this.data.indexQuery)
    const activeGroupKey = String(options.activeGroupKey != null ? options.activeGroupKey : (this.data.activeGroupKey || ''))
    const forceOpenTree = Boolean(query) || config.id !== 'all'
    const filteredGroups = buildFilteredKnowledgeGroups(this._groups, config, query)
    const availableGroups = filteredGroups.filter(group => group.matchCount > 0 && group.nodes.length)
    const activeIndexGroup = activeGroupKey ? availableGroups.find(group => String(group.key) === activeGroupKey) : null
    // 索引自己的搜索始终跨主题检索；只有未使用索引搜索时才跟随图谱当前主题范围。
    // 因此输入关键词只会替换索引结果，不会改写图谱场景。
    const scopedGroups = dedicatedQuery ? availableGroups : (activeIndexGroup ? [activeIndexGroup] : availableGroups)
    const limit = this._indexLimit || INITIAL_INDEX_LIMIT
    const indexRows = []

    scopedGroups.forEach((group, groupIndex) => {
      const byParent = new Map()
      group.nodes.forEach((node) => {
        const parentId = Number(node.parentId) || 0
        if (!byParent.has(parentId)) byParent.set(parentId, [])
        byParent.get(parentId).push(node)
      })
      const fullGroup = (this._groups || []).find(item => String(item.key) === String(group.key)) || group
      const fullNodes = Array.isArray(fullGroup.nodes) ? fullGroup.nodes : []
      const root = group.nodes.find(node => Number(node.knowledge_point_id) === Number(group.rootId))
      if (!root) return
      const walk = (node, siblingIndex = 0, siblingCount = 1, ancestorHasNext = []) => {
        const id = Number(node.knowledge_point_id)
        const children = byParent.get(id) || []
        const indexExpandable = children.length > 0
        const indexForcedOpen = indexExpandable && forceOpenTree
        const indexExpanded = indexExpandable && (indexForcedOpen || this._expandedNodeIds.has(id))
        const subtreeNodes = fullNodes.filter(candidate => Array.isArray(candidate.pathIds) && candidate.pathIds.some(pathId => Number(pathId) === id))
        const subtreeTotal = Math.max(1, subtreeNodes.length || Number(node.descendantCount || 0) + 1)
        const establishedCount = subtreeNodes.reduce((count, candidate) => count + (isEstablishedNode(candidate) ? 1 : 0), 0)
        let indexMetaText = `${node.statusText} · ${node.trainable_question_count} 题可练`
        if (node.contextOnly) indexMetaText = `路径 · ${children.length || node.visibleChildCount || 1} 个匹配分支`
        else if (node.hasChildren) indexMetaText = `${node.childCount} 个子节点 · ${branchStatusText(node)} · 已建立 ${establishedCount}/${subtreeTotal}`
        const indexSelected = Number(this._selectedId) === id
        let indexActionText = indexForcedOpen
          ? (node.contextOnly ? '路径' : '查看')
          : (indexExpandable ? (indexExpanded ? '收起' : '展开') : (node.hasChildren ? '父级' : '定位'))
        if (!indexExpandable && !node.hasChildren && indexSelected) indexActionText = '已定位'
        const depth = Math.max(0, Number(node.depth) || 0)
        const visualDepth = Math.min(depth, 5)
        const indexHasNextSibling = siblingIndex + 1 < siblingCount
        const indexAncestorGuides = ancestorHasNext
          .slice(1, visualDepth)
          .reduce((guides, hasNext, ancestorIndex) => {
            if (hasNext) guides.push({ left: INDEX_TREE_BASE_X + ancestorIndex * INDEX_TREE_STEP_X })
            return guides
          }, [])
        const iconKind = indexIconKind(node, depth, siblingIndex + groupIndex)
        indexRows.push({
          ...node,
          depth,
          indexExpandable,
          indexForcedOpen,
          indexExpanded,
          indexSelected,
          indexHasNextSibling,
          indexMetaText,
          indexActionText,
          indexIconKind: iconKind,
          indexIconSrc: indexIconSrc(iconKind),
          indexIndent: INDEX_CONTENT_BASE_INDENT + Math.max(0, Math.min(depth - 1, 4)) * INDEX_TREE_STEP_X,
          indexAncestorGuides,
          indexJointLeft: depth ? INDEX_TREE_BASE_X + Math.max(0, visualDepth - 1) * INDEX_TREE_STEP_X : 0,
          indexChildStemLeft: INDEX_TREE_BASE_X + Math.min(depth, 4) * INDEX_TREE_STEP_X,
          indexSearchTarget: Boolean(dedicatedQuery && node.matched),
          indexAriaAction: dedicatedQuery && node.matched
            ? '在图谱中查看'
            : (indexSelected && !indexExpandable && !node.hasChildren
              ? '已在图谱中定位'
              : (indexForcedOpen ? (node.contextOnly ? '匹配路径' : '在图谱中查看') : (indexExpandable ? (indexExpanded ? '收起' : '展开') : (node.hasChildren ? '父级路径' : '在图谱中定位')))),
        })
        if (indexExpanded) {
          const descendantAncestorFlags = ancestorHasNext.concat(indexHasNextSibling)
          children.forEach((child, childIndex) => walk(child, childIndex, children.length, descendantAncestorFlags))
        }
      }
      walk(root, 0, 1, [])
    })

    return {
      indexNodes: indexRows.slice(0, limit).map((row, rowIndex, visibleRows) => ({
        ...row,
        indexIsLastVisible: rowIndex === visibleRows.length - 1,
      })),
      indexCount: scopedGroups.reduce((count, group) => count + Number(group.matchCount || 0), 0),
      indexDisplayCount: indexRows.length,
      hasMore: indexRows.length > limit,
      indexSearchResultCount: availableGroups.reduce((count, group) => count + Number(group.matchCount || 0), 0),
    }
  },

  _applyIndexViewOnly(callback) {
    if (!this.data.subject) { if (typeof callback === 'function') callback(); return }
    const dedicatedQuery = normalizeSearchText(this.data.indexQuery)
    const effectiveQuery = dedicatedQuery || normalizeSearchText(this.data.query)
    const payload = this._buildIndexPayload({ query: effectiveQuery, dedicatedQuery, activeGroupKey: this.data.activeGroupKey })
    this.setData(payload, () => { if (typeof callback === 'function') callback() })
  },

  applyView(resetCamera = false, animateScene = resetCamera, callback) {
    if (!this.data.subject) return
    const config = FILTERS.find(item => item.id === this.data.filter) || FILTERS[0]
    const query = normalizeSearchText(this.data.query)
    this._filteredGroups = buildFilteredKnowledgeGroups(this._groups, config, query)

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
    const searchResultCount = availableGroups.reduce((count, group) => count + Number(group.matchCount || 0), 0)
    const effectiveIndexQuery = normalizeSearchText(this.data.indexQuery) || query
    const indexPayload = this._buildIndexPayload({ query: effectiveIndexQuery, dedicatedQuery: normalizeSearchText(this.data.indexQuery), activeGroupKey })
    const payload = {
      activeGroupKey,
      activeGroupName: activeGroup ? activeGroup.name : '',
      scene,
      groupChips,
      quickGroupChips,
      themeGroupCount: groupChips.length,
      themeSheetGroups,
      searchPending: normalizeSearchText(this.data.searchDraft) !== query,
      searchResultCount,
      selectedPoint: selectedBase && selectedVisible ? { ...selectedBase, matchedAlias: selectedVisible.matchedAlias || '' } : null,
      ...indexPayload,
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

  transitionLabelView(dataChanges = {}, callback) {
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
            if (typeof callback === 'function') callback()
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
    this._searchTimer = null
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    // 用户在防抖窗口内切换状态筛选时，直接采用输入框当前值，避免“文字已变但结果还是旧关键词”。
    this.transitionLabelView({ query: String(this.data.searchDraft || '').slice(0, 80), filter, searchPending: false, themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' })
  },
  searchPoints(event) {
    const searchDraft = String(event.detail.value || '').slice(0, 80)
    clearTimeout(this._searchTimer)
    this._searchTimer = null
    // 若上一轮搜索仍停留在“淡出但尚未提交”的 72ms 窗口，新输入直接取消
    // 旧提交，避免快速连续输入时闪过一次过期结果。
    const cancelLeavingTransition = Boolean(this._indexSearchLeaveTimer || this._indexSearchSettleTimer || this.data.indexResultsTransitioning)
    if (cancelLeavingTransition) {
      clearTimeout(this._indexSearchLeaveTimer)
      clearTimeout(this._indexSearchSettleTimer)
      this._indexSearchLeaveTimer = null
      this._indexSearchSettleTimer = null
      this._indexSearchTransitionToken = (this._indexSearchTransitionToken || 0) + 1
    }
    const draftQuery = normalizeSearchText(searchDraft)
    const committedQuery = normalizeSearchText(this.data.query)
    const changed = draftQuery !== committedQuery

    // 输入值与已应用查询分离：键入阶段只更新搜索框，不立刻重建图谱/索引。
    // 这样防抖期间旧结果保持稳定，避免每个字符都触发布局抖动。
    this.setData({
      searchDraft,
      searchPending: changed,
      ...(cancelLeavingTransition ? { indexResultsTransitioning: false, indexResultsPhase: '', indexResultsHeightStyle: '' } : {}),
      themeSheetOpen: false,
      themeSheetClosing: false,
      themeSheetPendingKey: '__idle__',
      themeQuery: '',
    })
    if (!changed) return

    const scheduledDraft = searchDraft
    const preserveIndexAnchor = Boolean(this.data.indexSearchOpen || this.data.indexSearchFocused)
    this._searchTimer = setTimeout(() => {
      this._searchTimer = null
      if (this._unloaded || String(this.data.searchDraft || '') !== scheduledDraft) return
      this._commitSearchQuery(scheduledDraft, { source: 'debounce', preserveIndexAnchor })
    }, SEARCH_DEBOUNCE_MS)
  },
  focusSearch() { if (!this.data.searchFocused) this.setData({ searchFocused: true, indexSearchFocused: false }) },
  toggleIndexSearch() {
    // 顶部搜索按钮既负责展开，也负责再次点击收起；查询条件保留，避免用户
    // 只是想腾出浏览空间时被迫丢失当前筛选结果。
    if (this.data.indexSearchOpen) {
      this.closeIndexSearch()
      return
    }
    this.openIndexSearch()
  },
  openIndexSearch() {
    // 索引内搜索就地展开，不触发页面滚动。输入框只在展开完成后获取焦点，
    // 减少键盘与布局同时变化造成的视觉跳动。
    const focus = () => {
      if (!this._unloaded && this.data.indexSearchOpen) {
        this.setData({ indexSearchFocused: true, searchFocused: false })
      }
    }
    if (this.data.indexSearchOpen) {
      focus()
      return
    }
    this.setData({ indexSearchOpen: true, indexSearchFocused: false, searchFocused: false }, () => {
      if (typeof wx.nextTick === 'function') wx.nextTick(focus)
      else setTimeout(focus, 0)
    })
  },
  focusIndexSearch() {
    if (!this.data.indexSearchFocused || this.data.searchFocused) this.setData({ indexSearchFocused: true, searchFocused: false })
  },
  blurIndexSearch() { if (this.data.indexSearchFocused) this.setData({ indexSearchFocused: false }) },
  indexSearchPoints(event) {
    const indexSearchDraft = String(event.detail.value || '').slice(0, 80)
    clearTimeout(this._indexSearchTimer)
    this._indexSearchTimer = null
    const cancelLeavingTransition = Boolean(this._indexSearchLeaveTimer || this._indexSearchSettleTimer || this.data.indexResultsTransitioning)
    if (cancelLeavingTransition) {
      clearTimeout(this._indexSearchLeaveTimer)
      clearTimeout(this._indexSearchSettleTimer)
      this._indexSearchLeaveTimer = null
      this._indexSearchSettleTimer = null
      this._indexSearchTransitionToken = (this._indexSearchTransitionToken || 0) + 1
    }
    const changed = normalizeSearchText(indexSearchDraft) !== normalizeSearchText(this.data.indexQuery)
    this.setData({
      indexSearchDraft,
      indexSearchPending: changed,
      ...(cancelLeavingTransition ? { indexResultsTransitioning: false, indexResultsPhase: '', indexResultsHeightStyle: '' } : {}),
    })
    if (!changed) return
    const scheduledDraft = indexSearchDraft
    this._indexSearchTimer = setTimeout(() => {
      this._indexSearchTimer = null
      if (this._unloaded || String(this.data.indexSearchDraft || '') !== scheduledDraft) return
      this._commitIndexSearchQuery(scheduledDraft, { source: 'debounce', preserveIndexAnchor: true })
    }, SEARCH_DEBOUNCE_MS)
  },
  submitIndexSearch(event) {
    const value = String(event && event.detail ? event.detail.value || '' : this.data.indexSearchDraft || '').slice(0, 80)
    clearTimeout(this._indexSearchTimer)
    this._indexSearchTimer = null
    this.setData({ indexSearchDraft: value }, () => this._commitIndexSearchQuery(value, { source: 'confirm', preserveIndexAnchor: true }))
  },
  closeIndexSearch() {
    if (!this.data.indexSearchOpen && !this.data.indexSearchFocused) return
    // 先撤销 focus 再收起搜索框，并主动关闭软键盘。保留 query，折叠后仍维持
    // 当前搜索结果，搜索按钮上的状态点会提示“仍有搜索条件生效”。
    this.setData({ indexSearchOpen: false, indexSearchFocused: false, searchFocused: false }, () => {
      if (typeof wx.hideKeyboard === 'function') {
        try { wx.hideKeyboard() } catch (error) { /* 键盘状态不影响搜索结果。 */ }
      }
      // Only release the layout floor after the user explicitly closes an idle
      // search. Active queries keep the floor even when the search bar is folded.
      if (!normalizeSearchText(this.data.indexQuery) && !normalizeSearchText(this.data.indexSearchDraft)) {
        this._releaseIndexSearchFloor()
      }
    })
  },
  clearIndexSearch() {
    clearTimeout(this._indexSearchTimer)
    this._indexSearchTimer = null
    this.setData({ indexSearchDraft: '', indexSearchPending: normalizeSearchText(this.data.indexQuery) !== '' }, () => {
      this._commitIndexSearchQuery('', { source: 'clear', preserveIndexAnchor: true })
      if (!this._unloaded) {
        const focus = () => this.setData({ indexSearchOpen: true, indexSearchFocused: true, searchFocused: false })
        if (typeof wx.nextTick === 'function') wx.nextTick(focus)
        else setTimeout(focus, 0)
      }
    })
  },
  blurSearch() { if (this.data.searchFocused) this.setData({ searchFocused: false }) },
  submitSearch(event) {
    const value = String(event && event.detail ? event.detail.value || '' : this.data.searchDraft || '').slice(0, 80)
    clearTimeout(this._searchTimer)
    this._searchTimer = null
    const preserveIndexAnchor = Boolean(this.data.indexSearchOpen || this.data.indexSearchFocused)
    this.setData({ searchDraft: value }, () => this._commitSearchQuery(value, { source: 'confirm', preserveIndexAnchor }))
  },
  clearSearch() {
    clearTimeout(this._searchTimer)
    this._searchTimer = null
    const preserveIndexAnchor = Boolean(this.data.indexSearchOpen || this.data.indexSearchFocused)
    this.setData({ searchDraft: '', searchPending: normalizeSearchText(this.data.query) !== '' }, () => this._commitSearchQuery('', { source: 'clear', preserveIndexAnchor }))
  },
  _indexSearchFloorPatch(height, allowGrow = true) {
    const measured = Math.max(0, Number(height) || 0)
    const current = Math.max(0, Number(this._indexSearchFloorHeight) || 0)
    const next = allowGrow ? Math.max(current, measured) : measured
    this._indexSearchFloorHeight = next > INDEX_SEARCH_FLOOR_EPSILON ? Math.ceil(next) : 0
    return {
      indexResultsFloorStyle: this._indexSearchFloorHeight ? `min-height:${this._indexSearchFloorHeight}px;` : '',
      indexResultsLayoutLocked: Boolean(this._indexSearchFloorHeight),
    }
  },
  _releaseIndexSearchFloor() {
    this._indexSearchFloorHeight = 0
    if (this.data.indexResultsFloorStyle || this.data.indexResultsLayoutLocked) {
      this.setData({ indexResultsFloorStyle: '', indexResultsLayoutLocked: false })
    }
  },
  _captureIndexSearchLayout(callback, preserveAnchor = false) {
    if (typeof callback !== 'function') return
    if (!wx.createSelectorQuery) { callback(null); return }
    try {
      let query = wx.createSelectorQuery()
      if (query.in) query = query.in(this)
      query.select('#knowledge-index-panel').boundingClientRect()
      query.select('#knowledge-index-results-content').boundingClientRect()
      query.selectViewport().scrollOffset()
      query.exec((result) => {
        const panel = result && result[0]
        const content = result && result[1]
        const viewport = result && result[2]
        callback({
          panelTop: preserveAnchor && panel && Number.isFinite(Number(panel.top)) ? Number(panel.top) : null,
          resultsHeight: content && Number.isFinite(Number(content.height)) ? Math.max(0, Number(content.height)) : 0,
          scrollTop: viewport && Number.isFinite(Number(viewport.scrollTop)) ? Number(viewport.scrollTop) : (Number(this._scrollTop) || 0),
        })
      })
    } catch (error) { callback(null) }
  },
  _measureIndexResultsHeight(callback) {
    if (typeof callback !== 'function') return
    if (!wx.createSelectorQuery) { callback(0); return }
    try {
      let query = wx.createSelectorQuery()
      if (query.in) query = query.in(this)
      query.select('#knowledge-index-results-content').boundingClientRect()
      query.exec((result) => {
        const rect = result && result[0]
        callback(rect && Number.isFinite(Number(rect.height)) ? Math.max(0, Number(rect.height)) : 0)
      })
    } catch (error) { callback(0) }
  },
  _restoreIndexSearchAnchor(anchor) {
    if (!anchor || anchor.panelTop == null || !wx.createSelectorQuery || typeof wx.pageScrollTo !== 'function') return
    const restore = () => {
      if (this._unloaded) return
      try {
        let query = wx.createSelectorQuery()
        if (query.in) query = query.in(this)
        query.select('#knowledge-index-panel').boundingClientRect()
        query.selectViewport().scrollOffset()
        query.exec((result) => {
          const panel = result && result[0]
          const viewport = result && result[1]
          if (!panel || !Number.isFinite(Number(panel.top))) return
          const currentScrollTop = viewport && Number.isFinite(Number(viewport.scrollTop)) ? Number(viewport.scrollTop) : (Number(this._scrollTop) || 0)
          const delta = Number(panel.top) - Number(anchor.panelTop)
          if (Math.abs(delta) <= INDEX_ANCHOR_EPSILON) return
          wx.pageScrollTo({ scrollTop: Math.max(0, currentScrollTop + delta), duration: 0 })
        })
      } catch (error) { /* 搜索布局锚定失败时不干预系统滚动。 */ }
    }
    if (typeof wx.nextTick === 'function') wx.nextTick(restore)
    else setTimeout(restore, 0)
  },
  _commitIndexSearchQuery(value, options = {}) {
    const nextQuery = String(value || '').slice(0, 80)
    const normalizedNext = normalizeSearchText(nextQuery)
    const normalizedCurrent = normalizeSearchText(this.data.indexQuery)
    clearTimeout(this._indexSearchTimer)
    this._indexSearchTimer = null

    if (normalizedNext === normalizedCurrent) {
      if (this.data.indexSearchPending || String(this.data.indexSearchDraft || '') !== nextQuery) {
        this.setData({ indexSearchDraft: nextQuery, indexSearchPending: false })
      }
      return
    }

    const token = (this._indexSearchTransitionToken || 0) + 1
    this._indexSearchTransitionToken = token
    clearTimeout(this._indexSearchLeaveTimer)
    clearTimeout(this._indexSearchSettleTimer)

    this._captureIndexSearchLayout((anchor) => {
      if (this._unloaded || token !== this._indexSearchTransitionToken) return
      const measuredOldHeight = anchor && anchor.resultsHeight > 0 ? anchor.resultsHeight : 0
      // The result area is allowed to grow during a search session, but never to
      // shrink. A no-result state therefore occupies the same document footprint
      // as the result tree it replaced, so the browser has no reason to clamp the
      // page back toward #atlas-shell.
      const floorPatch = this._indexSearchFloorPatch(measuredOldHeight, true)
      const oldHeight = Math.max(measuredOldHeight, Number(this._indexSearchFloorHeight) || 0)
      const leavingStyle = oldHeight > 0 ? `height:${oldHeight}px;overflow:hidden;` : ''
      this.setData({
        ...floorPatch,
        indexSearchPending: true,
        indexResultsTransitioning: true,
        indexResultsPhase: 'leaving',
        indexResultsHeightStyle: leavingStyle,
      }, () => {
        const commit = () => {
          if (this._unloaded || token !== this._indexSearchTransitionToken) return
          this._indexLimit = INITIAL_INDEX_LIMIT
          // 关键：这里只提交索引查询并重建索引列表。图谱 scene / 相机 / 当前图谱范围
          // 完全不动，用户输入或搜不到内容时不会再被带到图谱区域。
          this.setData({ indexQuery: nextQuery }, () => {
            this._applyIndexViewOnly(() => {
              if (this._unloaded || token !== this._indexSearchTransitionToken) return
              this._restoreIndexSearchAnchor(anchor)
              this._measureIndexResultsHeight((newHeight) => {
                if (this._unloaded || token !== this._indexSearchTransitionToken) return
                const nextFloorPatch = this._indexSearchFloorPatch(Math.max(oldHeight, newHeight), true)
                const targetHeight = Math.max(newHeight, Number(this._indexSearchFloorHeight) || 0, oldHeight)
                const heightStyle = oldHeight > 0 && targetHeight > 0 ? `height:${targetHeight}px;overflow:hidden;` : ''
                const stillPending = normalizeSearchText(this.data.indexSearchDraft) !== normalizedNext
                this.setData({
                  ...nextFloorPatch,
                  indexSearchPending: stillPending,
                  indexResultsPhase: 'entering',
                  indexResultsHeightStyle: heightStyle,
                }, () => {
                  this._restoreIndexSearchAnchor(anchor)
                  this._indexSearchSettleTimer = setTimeout(() => {
                    this._indexSearchSettleTimer = null
                    if (this._unloaded || token !== this._indexSearchTransitionToken) return
                    this.setData({
                      indexResultsTransitioning: false,
                      indexResultsPhase: '',
                      indexResultsHeightStyle: '',
                    }, () => this._restoreIndexSearchAnchor(anchor))
                  }, Math.max(INDEX_SEARCH_ENTER_MS, INDEX_SEARCH_HEIGHT_MS))
                })
              })
            })
          })
        }
        if (options.immediate || !oldHeight) commit()
        else {
          this._indexSearchLeaveTimer = setTimeout(() => {
            this._indexSearchLeaveTimer = null
            commit()
          }, INDEX_SEARCH_LEAVE_MS)
        }
      })
    }, Boolean(options.preserveIndexAnchor))
  },

  _commitSearchQuery(value, options = {}) {
    const nextQuery = String(value || '').slice(0, 80)
    const normalizedNext = normalizeSearchText(nextQuery)
    const normalizedCurrent = normalizeSearchText(this.data.query)
    clearTimeout(this._searchTimer)
    this._searchTimer = null

    if (normalizedNext === normalizedCurrent) {
      if (this.data.searchPending || String(this.data.searchDraft || '') !== nextQuery) {
        this.setData({ searchDraft: nextQuery, searchPending: false })
      }
      return
    }

    const token = (this._indexSearchTransitionToken || 0) + 1
    this._indexSearchTransitionToken = token
    clearTimeout(this._indexSearchLeaveTimer)
    clearTimeout(this._indexSearchSettleTimer)

    this._captureIndexSearchLayout((anchor) => {
      if (this._unloaded || token !== this._indexSearchTransitionToken) return
      const oldHeight = anchor && anchor.resultsHeight > 0 ? anchor.resultsHeight : 0
      const leavingStyle = oldHeight > 0 ? `height:${oldHeight}px;overflow:hidden;` : ''
      this.setData({
        searchPending: true,
        indexResultsTransitioning: true,
        indexResultsPhase: 'leaving',
        indexResultsHeightStyle: leavingStyle,
      }, () => {
        const commit = () => {
          if (this._unloaded || token !== this._indexSearchTransitionToken) return
          this._graphPage = 0
          this._indexLimit = INITIAL_INDEX_LIMIT
          this.setData({
            query: nextQuery,
            activeGroupKey: '',
            themeSheetOpen: false,
            themeSheetClosing: false,
            themeSheetPendingKey: '__idle__',
            themeQuery: '',
          }, () => {
            // 搜索只替换内容，不重置相机视角；图谱与索引一起更新但页面不被强制带走。
            this.applyView(false, false, () => {
              if (this._unloaded || token !== this._indexSearchTransitionToken) return
              this._restoreIndexSearchAnchor(anchor)
              this._measureIndexResultsHeight((newHeight) => {
                if (this._unloaded || token !== this._indexSearchTransitionToken) return
                const targetHeight = newHeight > 0 ? newHeight : oldHeight
                const heightStyle = oldHeight > 0 && targetHeight > 0 ? `height:${targetHeight}px;overflow:hidden;` : ''
                const stillPending = normalizeSearchText(this.data.searchDraft) !== normalizedNext
                this.setData({
                  searchPending: stillPending,
                  indexResultsPhase: 'entering',
                  indexResultsHeightStyle: heightStyle,
                }, () => {
                  this._restoreIndexSearchAnchor(anchor)
                  this._indexSearchSettleTimer = setTimeout(() => {
                    this._indexSearchSettleTimer = null
                    if (this._unloaded || token !== this._indexSearchTransitionToken) return
                    this.setData({
                      indexResultsTransitioning: false,
                      indexResultsPhase: '',
                      indexResultsHeightStyle: '',
                    }, () => this._restoreIndexSearchAnchor(anchor))
                  }, Math.max(INDEX_SEARCH_ENTER_MS, INDEX_SEARCH_HEIGHT_MS))
                })
              })
            })
          })
        }
        if (options.immediate || !oldHeight) commit()
        else {
          this._indexSearchLeaveTimer = setTimeout(() => {
            this._indexSearchLeaveTimer = null
            commit()
          }, INDEX_SEARCH_LEAVE_MS)
        }
      })
    }, Boolean(options.preserveIndexAnchor))
  },
  resetFilters() {
    clearTimeout(this._searchTimer)
    this._searchTimer = null
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    this.setData({ filter: 'all', query: '', searchDraft: '', searchPending: false, activeGroupKey: '', themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' }, () => this.applyView(true))
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
  openGroup(key, callback) {
    const normalized = String(key || '')
    const targetGroup = normalized
      ? (this._filteredGroups || []).find(group => String(group.key) === normalized && group.matchCount > 0 && group.nodes.length)
      : null
    if (normalized && !targetGroup) { if (typeof callback === 'function') callback(); return }
    if (targetGroup && targetGroup.rootNode && !targetGroup.rootNode.hasChildren) {
      this.locatePointById(Number(targetGroup.rootId), { afterRender: callback })
      return
    }
    const targetFocusId = targetGroup ? Number(targetGroup.rootId) || 0 : 0
    if (normalized === this.data.activeGroupKey && Number(this._focusNodeId) === targetFocusId) { if (typeof callback === 'function') callback(); return }
    this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
    this._focusNodeId = targetFocusId
    if (targetFocusId) this._expandedNodeIds.add(targetFocusId)
    if (normalized) this.rememberGroup(normalized)
    const quickGroupChips = buildQuickGroupChips(this.data.groupChips, normalized, this._recentGroupKeys)
    this.transitionLabelView({ activeGroupKey: normalized, quickGroupChips }, callback)
  },
  showOverview(callback) {
    this._focusNodeId = 0
    this.openGroup('', callback)
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
  navigateToFocus(groupKey, focusNodeId, callback) {
    const normalizedGroupKey = String(groupKey || '')
    const nextFocusId = Math.max(0, Number(focusNodeId) || 0)
    if (!normalizedGroupKey || !nextFocusId) {
      this._focusNodeId = 0
      this.openGroup('', callback)
      return
    }
    const group = (this._filteredGroups || []).find(item => String(item.key) === normalizedGroupKey && item.matchCount > 0)
    const node = group && group.nodes.find(item => Number(item.knowledge_point_id) === nextFocusId)
    if (!group || !node) { if (typeof callback === 'function') callback(); return }
    if (String(this.data.activeGroupKey) === normalizedGroupKey && Number(this._focusNodeId) === nextFocusId) { if (typeof callback === 'function') callback(); return }
    this._graphPage = 0
    this._selectedId = 0
    this._focusNodeId = nextFocusId
    const base = this._nodeById && this._nodeById.get(nextFocusId)
    ;(base && Array.isArray(base.pathIds) ? base.pathIds : [nextFocusId]).forEach(id => this._expandedNodeIds.add(Number(id)))
    const quickGroupChips = buildQuickGroupChips(this.data.groupChips, normalizedGroupKey, this._recentGroupKeys)
    this.transitionLabelView({ activeGroupKey: normalizedGroupKey, quickGroupChips }, callback)
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
  _captureIndexViewportAnchor(id, callback) {
    if (typeof callback !== 'function') return
    if (!wx.createSelectorQuery) { callback(null); return }
    try {
      let query = wx.createSelectorQuery()
      if (query.in) query = query.in(this)
      query.select(`#knowledge-index-node-${Number(id)}`).boundingClientRect()
      query.selectViewport().scrollOffset()
      query.exec((result) => {
        const rect = result && result[0]
        const viewport = result && result[1]
        if (!rect || !Number.isFinite(Number(rect.top))) { callback(null); return }
        callback({
          top: Number(rect.top),
          scrollTop: viewport && Number.isFinite(Number(viewport.scrollTop)) ? Number(viewport.scrollTop) : (Number(this._scrollTop) || 0),
        })
      })
    } catch (error) { callback(null) }
  },
  _restoreIndexViewportAnchor(id, anchor) {
    if (!anchor || !wx.createSelectorQuery || typeof wx.pageScrollTo !== 'function') return
    const restore = () => {
      if (this._unloaded) return
      try {
        let query = wx.createSelectorQuery()
        if (query.in) query = query.in(this)
        query.select(`#knowledge-index-node-${Number(id)}`).boundingClientRect()
        query.selectViewport().scrollOffset()
        query.exec((result) => {
          const rect = result && result[0]
          const viewport = result && result[1]
          if (!rect || !Number.isFinite(Number(rect.top))) return
          const currentScrollTop = viewport && Number.isFinite(Number(viewport.scrollTop)) ? Number(viewport.scrollTop) : (Number(this._scrollTop) || 0)
          const delta = Number(rect.top) - Number(anchor.top)
          if (Math.abs(delta) <= INDEX_ANCHOR_EPSILON) return
          wx.pageScrollTo({ scrollTop: Math.max(0, currentScrollTop + delta), duration: 0 })
        })
      } catch (error) { /* 锚点恢复失败时保持系统当前滚动位置，不做二次跳转。 */ }
    }
    if (typeof wx.nextTick === 'function') wx.nextTick(restore)
    else setTimeout(restore, 0)
  },
  _runIndexInteraction(id) {
    const pointId = Number(id)
    if (!pointId || Number(this.data.indexNavigatingId)) return
    const dedicatedQuery = normalizeSearchText(this.data.indexQuery)
    const row = (Array.isArray(this.data.indexNodes) ? this.data.indexNodes : []).find(item => Number(item.knowledge_point_id) === pointId)
    if (dedicatedQuery) {
      // 搜索路径节点仅用于说明层级；真正命中的标签才会显式驱动图谱。
      if (!row || !row.matched) return
      this._navigateFromIndexSearch(pointId)
      return
    }
    this._captureIndexViewportAnchor(pointId, (anchor) => {
      if (this._unloaded) return
      this.activateIndexNode(pointId, {
        keepViewport: true,
        afterRender: () => this._restoreIndexViewportAnchor(pointId, anchor),
      })
    })
  },
  _navigateFromIndexSearch(id) {
    const pointId = Number(id)
    const point = this._nodeById && this._nodeById.get(pointId)
    if (!point) return
    const sourceGroup = (this._groups || []).find(group => String(group.key) === String(point.groupKey))
    if (!sourceGroup) return

    clearTimeout(this._indexNavigateTimer)
    if (typeof wx.hideKeyboard === 'function') {
      try { wx.hideKeyboard() } catch (error) { /* 键盘关闭失败不阻断定位。 */ }
    }
    this.setData({ indexNavigatingId: pointId, indexSearchFocused: false, searchFocused: false })

    this._indexNavigateTimer = setTimeout(() => {
      this._indexNavigateTimer = null
      if (this._unloaded) return

      // 只有用户明确点击搜索结果时，才把图谱切到该知识点。若当前全局筛选
      // 会隐藏目标，则只清除冲突条件，不破坏索引搜索关键词。
      const currentConfig = FILTERS.find(item => item.id === this.data.filter) || FILTERS[0]
      const targetFilter = currentConfig.statuses && !currentConfig.statuses.includes(point.status) ? 'all' : this.data.filter
      const currentGraphQuery = String(this.data.query || '')
      const targetGraphQuery = currentGraphQuery && !pointSearchMatch(point, currentGraphQuery).matched ? '' : currentGraphQuery
      const targetConfig = FILTERS.find(item => item.id === targetFilter) || FILTERS[0]

      this._selectedId = pointId
      ;(Array.isArray(point.pathIds) ? point.pathIds : []).forEach(pathId => this._expandedNodeIds.add(Number(pathId)))

      let activeGroupKey = String(point.groupKey || '')
      if (point.hasChildren) {
        this._focusNodeId = pointId
        this._graphPage = 0
      } else {
        const parentId = Number(point.parentId) || 0
        if (parentId) {
          this._focusNodeId = parentId
          const siblings = sourceGroup.nodes.filter((item) => {
            if (Number(item.parentId) !== parentId) return false
            if (targetConfig.statuses && !targetConfig.statuses.includes(item.status)) return false
            return pointSearchMatch(item, targetGraphQuery).matched
          })
          const siblingIndex = Math.max(0, siblings.findIndex(item => Number(item.knowledge_point_id) === pointId))
          this._graphPage = Math.floor(siblingIndex / POINTS_PER_PAGE)
        } else {
          this._focusNodeId = 0
          activeGroupKey = ''
          const visibleGroups = (this._groups || []).filter((group) => group.nodes.some((item) => {
            if (targetConfig.statuses && !targetConfig.statuses.includes(item.status)) return false
            return pointSearchMatch(item, targetGraphQuery).matched
          }))
          const groupIndex = Math.max(0, visibleGroups.findIndex(group => String(group.key) === String(point.groupKey)))
          this._graphPage = Math.floor(groupIndex / POINTS_PER_PAGE)
        }
      }

      this.setData({
        filter: targetFilter,
        query: targetGraphQuery,
        searchDraft: targetGraphQuery,
        searchPending: false,
        activeGroupKey,
      }, () => {
        this.applyView(true, true, () => {
          const scrollToGraph = () => {
            if (this._unloaded) return
            if (typeof wx.pageScrollTo === 'function') wx.pageScrollTo({ selector: '#atlas-shell', duration: INDEX_GRAPH_SCROLL_MS })
            setTimeout(() => {
              if (!this._unloaded && Number(this.data.indexNavigatingId) === pointId) this.setData({ indexNavigatingId: 0 })
            }, INDEX_GRAPH_SCROLL_MS + 90)
          }
          if (typeof wx.nextTick === 'function') wx.nextTick(scrollToGraph)
          else setTimeout(scrollToGraph, 0)
        })
      })
    }, INDEX_NAVIGATE_FEEDBACK_MS)
  },
  handleIndexRowTap(event) { this._runIndexInteraction(Number(event.currentTarget.dataset.id)) },
  handleIndexActionTap(event) { this._runIndexInteraction(Number(event.currentTarget.dataset.id)) },
  activateIndexNode(id, options = {}) {
    const done = typeof options.afterRender === 'function' ? options.afterRender : () => {}
    const node = this._nodeById && this._nodeById.get(Number(id))
    if (!node) { done(); return }
    const group = (this._filteredGroups || []).find(item => String(item.key) === String(node.groupKey))
    const visibleChildren = group ? group.nodes.filter(item => Number(item.parentId) === Number(id)) : []
    if (visibleChildren.length) {
      const forceOpenTree = Boolean(normalizeSearchText(this.data.query)) || this.data.filter !== 'all'
      if (forceOpenTree) {
        this.navigateToFocus(String(node.groupKey), Number(id), done)
        return
      }
      if (this._expandedNodeIds.has(Number(id))) this._expandedNodeIds.delete(Number(id))
      else this._expandedNodeIds.add(Number(id))
      this._indexLimit = Math.max(INITIAL_INDEX_LIMIT, Number(this._indexLimit) || INITIAL_INDEX_LIMIT)
      this.applyView(false, false, done)
      return
    }
    // 搜索/状态筛选下父节点可能仅作为路径上下文保留。此时点击仍更新图谱父级，
    // 但索引交互会保持当前视口，不再把用户强制带离正在浏览的位置。
    if (node.hasChildren) {
      this.navigateToFocus(String(node.groupKey), Number(id), done)
      return
    }
    this.locatePointById(Number(id), { scrollToGraph: !options.keepViewport, afterRender: done })
  },
  locatePoint(event) { this.locatePointById(Number(event.currentTarget.dataset.id)) },
  locatePointById(id, options = {}) {
    const point = this._nodeById && this._nodeById.get(Number(id))
    if (!point) { if (typeof options.afterRender === 'function') options.afterRender(); return }
    const group = (this._filteredGroups || []).find(item => String(item.key) === String(point.groupKey))
    if (!group) { if (typeof options.afterRender === 'function') options.afterRender(); return }

    this._selectedId = Number(point.knowledge_point_id)
    this._indexLimit = Math.max(INITIAL_INDEX_LIMIT, Number(this._indexLimit) || INITIAL_INDEX_LIMIT)
    ;(Array.isArray(point.pathIds) ? point.pathIds : []).forEach(pathId => this._expandedNodeIds.add(Number(pathId)))

    const finish = () => {
      if (typeof options.afterRender === 'function') options.afterRender()
      if (options.scrollToGraph === false || typeof wx.pageScrollTo !== 'function') return
      wx.pageScrollTo({ selector: '#atlas-shell', duration: 220 })
    }
    const parentId = Number(point.parentId) || 0
    if (parentId) {
      const siblings = group.nodes.filter(item => Number(item.parentId) === parentId)
      const index = siblings.findIndex(item => Number(item.knowledge_point_id) === Number(point.knowledge_point_id))
      if (index < 0) { finish(); return }
      this._focusNodeId = parentId
      this._graphPage = Math.floor(index / POINTS_PER_PAGE)
      this.setData({ activeGroupKey: String(point.groupKey) }, () => this.applyView(true, options.scrollToGraph !== false, finish))
    } else {
      const availableGroups = (this._filteredGroups || []).filter(item => item.matchCount > 0 && item.nodes.length)
      const groupIndex = availableGroups.findIndex(item => String(item.key) === String(point.groupKey))
      if (groupIndex < 0) { finish(); return }
      this._focusNodeId = 0
      this._graphPage = Math.floor(groupIndex / POINTS_PER_PAGE)
      this.setData({ activeGroupKey: '' }, () => this.applyView(true, options.scrollToGraph !== false, finish))
    }
  },

  loadMore() { this._indexLimit = (this._indexLimit || INITIAL_INDEX_LIMIT) + INITIAL_INDEX_LIMIT; this._applyIndexViewOnly() },
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

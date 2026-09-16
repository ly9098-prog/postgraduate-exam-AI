const api = require('../../../utils/api')
const { knowledgePracticeSync } = require('../../../utils/storage')
const { buildKnowledgeGroups, summarizeGroups } = require('./tree-groups')
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
const INDEX_DETAIL_SCROLL_MS = 360
const INDEX_DETAIL_SCROLL_TOP_GAP = 12
const INDEX_DETAIL_REVEAL_MS = 320
const INDEX_SEARCH_RETENTION_EPSILON = 1
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
chapterGraduation: summarizeGroups([]).summary,
filters: FILTERS.map(item => ({ id: item.id, label: item.label, count: 0 })),
filter: 'all', query: '', searchDraft: '', searchFocused: false, searchPending: false, searchResultCount: 0, activeGroupKey: '', activeGroupName: '', indexScopeGroupKey: '',
groupChips: [], quickGroupChips: [], themeGroupCount: 0, themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '', themeSheetGroups: [],
scene: { nodes: [], edges: [], page: 0, pageCount: 1, focused: false },
pageEntered: false, sceneAnimating: false, themeSwitching: false, themeSwitchPhase: '', selectionSwitching: false, selectionSwitchPhase: '', graphInteracting: false,
stageStyle: '', zoomText: '100%', zoomInDisabled: false, zoomOutDisabled: true, selectedPoint: null,
indexDetailRevealPhase: '', indexDetailRevealStyle: '',
indexNodes: [], indexCount: 0, indexDisplayCount: 0, hasMore: false, indexSearchOpen: false, indexSearchFocused: false,
indexQuery: '', indexSearchDraft: '', indexSearchPending: false, indexSearchResultCount: 0, indexNavigatingId: 0,
indexResultsTransitioning: false, indexResultsPhase: '', indexResultsHeightStyle: '', indexScrollRetentionStyle: '',
practiceLaunching: false, practiceLaunchingId: 0,
},
onLoad(options) {
this.subjectId = Number(options && options.subject_id)
this._viewStateStorageKey = Number.isInteger(this.subjectId) && this.subjectId > 0
? `knowledgeSubjectViewState:${this.subjectId}`
: ''
this._pendingReturnState = null
this._returnRefreshTimer = null
this._returnSyncRetryTimer = null
this._practiceLaunchFeedbackTimer = null
this._practiceNavigationPending = false
this._detailNavigationPending = false
this._indexDetailScrollToken = 0
this._indexDetailRevealToken = 0
this._indexDetailRevealTimer = null
this._pageVisible = true
this._focusNodeId = 0
this._expandedNodeIds = new Set()
this._indexSearchFootprintHeight = 0
this._indexSearchRetentionHeight = 0
let width = 375
try {
const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
width = Number(info.windowWidth) || width
} catch (error) { }
this._frame = { left: 0, top: 0, width: width * 702 / 750, height: width * 860 / 750 }
this._camera = fitCamera(this._frame)
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
if (persistedState) {
this._pendingInitialViewState = persistedState
this._primeViewState(persistedState, false)
}
this._initialLoadState = persistedState
this._readyForViewWork = false
this._refreshAfterReturn = false
},
onReady() {
if (this._unloaded) return
this._readyForViewWork = true
const start = () => {
if (this._unloaded || this._pageVisible === false) return
this.setCamera(this._camera)
this.measureViewport(!this._pendingInitialViewState)
const state = this._initialLoadState || null
this._initialLoadState = null
this.loadMap(true, { preserveViewState: state })
}
if (typeof wx.nextTick === 'function') wx.nextTick(start)
else setTimeout(start, 0)
},
onShow() {
this._pageVisible = true
this._practiceNavigationPending = false
this._detailNavigationPending = false
if (this.data.indexDetailRevealPhase || this.data.indexDetailRevealStyle) {
this.setData({ indexDetailRevealPhase: '', indexDetailRevealStyle: '' })
}
if (this._practiceLaunchFeedbackTimer) {
clearTimeout(this._practiceLaunchFeedbackTimer)
this._practiceLaunchFeedbackTimer = null
}
if (!this._readyForViewWork || !this._loadedOnce) return
if (this.data.practiceLaunching || this.data.practiceLaunchingId) {
this.setData({ practiceLaunching: false, practiceLaunchingId: 0 })
}
if (!this._refreshAfterReturn) {
this._pendingReturnState = null
return
}
this._refreshAfterReturn = false
const restoreState = this._pendingReturnState || this._captureViewState()
this._pendingReturnState = null
clearTimeout(this._returnRefreshTimer)
clearTimeout(this._returnSyncRetryTimer)
this._returnRefreshTimer = setTimeout(() => {
this._returnRefreshTimer = null
if (!this._unloaded && this._pageVisible !== false) this._refreshMapAfterPractice(restoreState, 0)
}, RETURN_REFRESH_DELAY_MS)
},
onPageScroll(event) { this._scrollTop = Number(event.scrollTop) || 0 },
onHide() {
this._pageVisible = false
this._requestId = (this._requestId || 0) + 1
clearTimeout(this._cameraTimer)
clearTimeout(this._inertiaTimer)
clearTimeout(this._searchTimer)
clearTimeout(this._indexSearchTimer)
clearTimeout(this._indexNavigateTimer)
this._indexDetailScrollToken = (this._indexDetailScrollToken || 0) + 1
this._indexDetailRevealToken = (this._indexDetailRevealToken || 0) + 1
clearTimeout(this._indexDetailRevealTimer)
this._indexDetailRevealTimer = null
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
clearTimeout(this._returnSyncRetryTimer)
this._returnSyncRetryTimer = null
clearTimeout(this._practiceLaunchFeedbackTimer)
this._indexNavigateTimer = null
this._practiceLaunchFeedbackTimer = null
},
onResize() { this.measureViewport(true) },
onUnload() {
this._pageVisible = false
this._unloaded = true
this._requestId = (this._requestId || 0) + 1
clearTimeout(this._cameraTimer)
clearTimeout(this._inertiaTimer)
clearTimeout(this._searchTimer)
clearTimeout(this._indexSearchTimer)
clearTimeout(this._indexNavigateTimer)
this._indexDetailScrollToken = (this._indexDetailScrollToken || 0) + 1
this._indexDetailRevealToken = (this._indexDetailRevealToken || 0) + 1
clearTimeout(this._indexDetailRevealTimer)
this._indexDetailRevealTimer = null
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
clearTimeout(this._returnSyncRetryTimer)
this._returnSyncRetryTimer = null
clearTimeout(this._practiceLaunchFeedbackTimer)
this._practiceLaunchFeedbackTimer = null
this._practiceNavigationPending = false
this._detailNavigationPending = false
},
async _refreshMapAfterPractice(restoreState, attempt = 0) {
if (this._unloaded || this._pageVisible === false) return
try {
await this.loadMap(false, { preserveViewState: restoreState })
} catch (error) { }
if (this._unloaded || this._pageVisible === false) return
if (!knowledgePracticeSync.hasPending(this.subjectId) || attempt >= 2) return
const delays = [900, 1800]
clearTimeout(this._returnSyncRetryTimer)
this._returnSyncRetryTimer = setTimeout(() => {
this._returnSyncRetryTimer = null
this._refreshMapAfterPractice(restoreState, attempt + 1)
}, delays[attempt] || 1800)
},
onPullDownRefresh() {
Promise.resolve(this.loadMap(false, { preserveViewState: this._captureViewState() })).then(() => wx.stopPullDownRefresh(), () => wx.stopPullDownRefresh())
},
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
indexScopeGroupKey: String(this.data.indexScopeGroupKey || ''),
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
try { wx.setStorageSync(this._viewStateStorageKey, snapshot) } catch (error) { }
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
indexScopeGroupKey: String(state.indexScopeGroupKey != null ? state.indexScopeGroupKey : (state.activeGroupKey || '')),
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
_primeViewState(state, publish = true) {
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
if (publish) this.setData({ ...this._viewStateDataPatch(state), ...this.cameraPayload(true) })
},
_restoreScrollPosition() {
// Let the native page stack preserve scroll position. Manual pageScrollTo during
// route creation/return can race the WebView lifecycle in DevTools.
},
async loadMap(showLoading = true, options = {}) {
if (!Number.isInteger(this.subjectId) || this.subjectId <= 0) return
const requestId = (this._requestId || 0) + 1
this._requestId = requestId
if (showLoading) this.setData({ loading: !this._loadedOnce, error: '', refreshError: '' })
try {
const data = await api.get(`/knowledge-map/subjects/${this.subjectId}`)
if (this._unloaded || this._pageVisible === false || requestId !== this._requestId) return
if (!data || !data.subject) throw new Error('知识图谱暂不可用')
const pendingReceipts = knowledgePracticeSync.getForSubject(this.subjectId)
const receiptByPointId = new Map()
pendingReceipts.forEach((receipt) => {
const id = Number(receipt && receipt.knowledgePointId) || 0
if (id && !receiptByPointId.has(id)) receiptByPointId.set(id, receipt)
})
const resolvedReceipts = []
this._nodes = (Array.isArray(data.nodes) ? data.nodes : []).map((item) => {
const score = percent(item.mastery_score)
const backendAccuracy = accuracyPercent(item.accuracy)
const backendAttemptCount = nonnegative(item.attempt_count)
const backendStatus = STATUS_TEXT[item.status] ? item.status : 'no_data'
const pointId = Number(item.knowledge_point_id) || 0
const receipt = receiptByPointId.get(pointId) || null
const backendHasEvidence = backendAttemptCount > 0 || backendAccuracy != null || backendStatus !== 'no_data'
if (receipt && backendHasEvidence) resolvedReceipts.push(receipt)
const pendingSync = Boolean(receipt && !backendHasEvidence)
const receiptAnswered = receipt ? Math.max(0, Number(receipt.correctCount) || 0) + Math.max(0, Number(receipt.wrongCount) || 0) : 0
const receiptAccuracy = receiptAnswered > 0 ? percent((Number(receipt.correctCount) || 0) / receiptAnswered * 100) : null
const status = pendingSync || (backendStatus === 'no_data' && backendAttemptCount > 0) ? 'insufficient' : backendStatus
const attemptCount = pendingSync ? Math.max(backendAttemptCount, Number(receipt.answeredCount) || receiptAnswered) : backendAttemptCount
const aliases = Array.isArray(item.aliases)
? item.aliases.map(alias => String(alias || '').trim()).filter(Boolean)
: []
return {
...item, aliases, name: String(item.name || '未命名知识点'), status,
statusText: pendingSync ? '已作答 · 待更新' : STATUS_TEXT[status],
tone: status === 'weak' || status === 'developing' ? 'weak' : (status === 'good' || status === 'mastered' ? 'stable' : 'unseen'),
scoreText: score == null ? '待建立' : `${score}%`, hasScore: score != null,
accuracyText: pendingSync ? (receiptAccuracy == null ? '已作答' : `${receiptAccuracy}%`) : (backendAccuracy == null ? '暂无' : `${backendAccuracy}%`),
attempt_count: attemptCount,
pendingSync,
trainable_question_count: nonnegative(item.trainable_question_count),
hasPractice: nonnegative(item.trainable_question_count) > 0,
}
})
if (resolvedReceipts.length) knowledgePracticeSync.remove(resolvedReceipts)
this._groups = buildKnowledgeGroups(this._nodes, data.subject)
const graduation = summarizeGroups(this._groups)
this._groups = graduation.items
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
chapterGraduation: graduation.summary,
...(preserveViewState ? this._viewStateDataPatch(preserveViewState) : {}),
...(preserveViewState ? this.cameraPayload(true) : {}),
}, () => this.applyView(firstLoad && !preserveViewState, firstLoad && !preserveViewState, () => {
if (firstLoad) this.enterPage()
if (preserveViewState) this._restoreScrollPosition(preserveViewState)
this._pendingInitialViewState = null
}))
} catch (error) {
if (this._unloaded || this._pageVisible === false || requestId !== this._requestId) return
const message = api.getErrorMessage(error)
this.setData(this.data.subject ? { loading: false, refreshError: message } : { loading: false, error: message })
}
},
enterPage() {
clearTimeout(this._entryTimer)
const reveal = () => {
this._entryTimer = setTimeout(() => {
this._entryTimer = null
if (!this._unloaded && this._pageVisible !== false) this.setData({ pageEntered: true })
}, 24)
}
if (wx.nextTick) wx.nextTick(reveal)
else reveal()
},
_buildIndexPayload(options = {}) {
const config = FILTERS.find(item => item.id === this.data.filter) || FILTERS[0]
const query = normalizeSearchText(options.query != null ? options.query : (this.data.indexQuery || this.data.query))
const dedicatedQuery = normalizeSearchText(options.dedicatedQuery != null ? options.dedicatedQuery : this.data.indexQuery)
const indexScopeGroupKey = String(options.indexScopeGroupKey != null ? options.indexScopeGroupKey : (this.data.indexScopeGroupKey || ''))
const forceOpenTree = Boolean(query) || config.id !== 'all'
const filteredGroups = buildFilteredKnowledgeGroups(this._groups, config, query)
const availableGroups = filteredGroups.filter(group => group.matchCount > 0 && group.nodes.length)
const activeIndexGroup = indexScopeGroupKey ? availableGroups.find(group => String(group.key) === indexScopeGroupKey) : null
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
let indexMetaText = node.pendingSync
? `${node.attempt_count} 题已记录 · 待后台汇总`
: `${node.statusText} · ${node.trainable_question_count} 题可练`
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
const payload = this._buildIndexPayload({ query: effectiveQuery, dedicatedQuery, indexScopeGroupKey: this.data.indexScopeGroupKey })
this.setData(payload, () => { if (typeof callback === 'function') callback() })
},
applyView(resetCamera = false, animateScene = resetCamera, callback) {
if (!this.data.subject) return
const config = FILTERS.find(item => item.id === this.data.filter) || FILTERS[0]
const query = normalizeSearchText(this.data.query)
this._filteredGroups = buildFilteredKnowledgeGroups(this._groups, config, query)
const availableGroups = this._filteredGroups.filter(group => group.matchCount > 0 && group.nodes.length)
let indexScopeGroupKey = String(this.data.indexScopeGroupKey || '')
if (indexScopeGroupKey && !availableGroups.some(group => String(group.key) === indexScopeGroupKey)) indexScopeGroupKey = ''
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
graduationState: group.graduation ? group.graduation.state : 'unavailable',
graduationLabel: group.graduation ? group.graduation.label : '暂无判定',
graduationReason: group.graduation ? group.graduation.reason : '',
graduated: Boolean(group.graduation && group.graduation.graduated),
}
})
const quickGroupChips = buildQuickGroupChips(groupChips, activeGroupKey, this._recentGroupKeys)
const themeSheetGroups = groupChips.filter(group => themeSearchMatch(group, this.data.themeQuery))
const activeGroup = groupChips.find(group => group.key === activeGroupKey)
const searchResultCount = availableGroups.reduce((count, group) => count + Number(group.matchCount || 0), 0)
const effectiveIndexQuery = normalizeSearchText(this.data.indexQuery) || query
const indexPayload = this._buildIndexPayload({ query: effectiveIndexQuery, dedicatedQuery: normalizeSearchText(this.data.indexQuery), indexScopeGroupKey })
const payload = {
activeGroupKey,
activeGroupName: activeGroup ? activeGroup.name : '',
indexScopeGroupKey,
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
const next = () => { if (!this._unloaded && this._pageVisible !== false) this.measureViewport(false) }
if (wx.nextTick) wx.nextTick(next)
else next()
if (animateScene) {
clearTimeout(this._sceneAnimationTimer)
this._sceneAnimationTimer = setTimeout(() => {
this._sceneAnimationTimer = null
if (!this._unloaded && this._pageVisible !== false) this.setData({ sceneAnimating: false })
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
this.applyView(false, false, () => {
if (this._unloaded) return
this.setData({ themeSwitchPhase: 'entering' }, () => {
if (typeof callback === 'function') callback()
this._themeTransitionTimer = setTimeout(() => {
this._themeTransitionTimer = null
if (!this._unloaded && this._pageVisible !== false) this.setData({ themeSwitching: false, themeSwitchPhase: '' })
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
this.transitionLabelView({ query: String(this.data.searchDraft || '').slice(0, 80), filter, searchPending: false, themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' })
},
searchPoints(event) {
const searchDraft = String(event.detail.value || '').slice(0, 80)
clearTimeout(this._searchTimer)
this._searchTimer = null
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
if (this._unloaded || this._pageVisible === false || String(this.data.searchDraft || '') !== scheduledDraft) return
this._commitSearchQuery(scheduledDraft, { source: 'debounce', preserveIndexAnchor })
}, SEARCH_DEBOUNCE_MS)
},
focusSearch() { if (!this.data.searchFocused) this.setData({ searchFocused: true, indexSearchFocused: false }) },
toggleIndexSearch() {
if (this.data.indexSearchOpen) {
this.closeIndexSearch()
return
}
this.openIndexSearch()
},
openIndexSearch() {
const focus = () => {
if (!this._unloaded && this._pageVisible !== false && this.data.indexSearchOpen) {
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
if (this._unloaded || this._pageVisible === false || String(this.data.indexSearchDraft || '') !== scheduledDraft) return
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
this.setData({ indexSearchOpen: false, indexSearchFocused: false, searchFocused: false }, () => {
if (typeof wx.hideKeyboard === 'function') {
try { wx.hideKeyboard() } catch (error) { }
}
if (!normalizeSearchText(this.data.indexQuery) && !normalizeSearchText(this.data.indexSearchDraft)) {
this._releaseIndexSearchRetention()
}
})
},
clearIndexSearch() {
clearTimeout(this._indexSearchTimer)
this._indexSearchTimer = null
this.setData({ indexSearchDraft: '', indexSearchPending: normalizeSearchText(this.data.indexQuery) !== '' }, () => {
this._commitIndexSearchQuery('', { source: 'clear', preserveIndexAnchor: true })
if (!this._unloaded && this._pageVisible !== false) {
const focus = () => { if (!this._unloaded && this._pageVisible !== false) this.setData({ indexSearchOpen: true, indexSearchFocused: true, searchFocused: false }) }
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
_indexSearchRetentionPatch(height) {
const next = Math.max(0, Number(height) || 0)
this._indexSearchRetentionHeight = next > INDEX_SEARCH_RETENTION_EPSILON ? Math.ceil(next) : 0
return {
indexScrollRetentionStyle: this._indexSearchRetentionHeight ? `height:${this._indexSearchRetentionHeight}px;` : '',
}
},
_releaseIndexSearchRetention() {
this._indexSearchFootprintHeight = 0
this._indexSearchRetentionHeight = 0
if (this.data.indexScrollRetentionStyle) this.setData({ indexScrollRetentionStyle: '' })
},
_capIndexSearchFootprint(anchor, footprint) {
const raw = Math.max(0, Number(footprint) || 0)
if (!anchor || anchor.panelTop == null || !anchor.viewportHeight || !anchor.panelHeight) return raw
const chromeHeight = Math.max(0, Number(anchor.panelHeight) - Math.max(0, Number(anchor.resultsHeight) || 0))
const viewportNeed = Math.max(0, Number(anchor.viewportHeight) - Number(anchor.panelTop) - chromeHeight + 24)
return Math.min(raw, Math.max(Math.max(0, Number(anchor.resultsHeight) || 0), viewportNeed))
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
let viewportHeight = 0
try {
const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
viewportHeight = Math.max(0, Number(info && info.windowHeight) || 0)
} catch (error) { }
callback({
panelTop: preserveAnchor && panel && Number.isFinite(Number(panel.top)) ? Number(panel.top) : null,
panelHeight: panel && Number.isFinite(Number(panel.height)) ? Math.max(0, Number(panel.height)) : 0,
resultsHeight: content && Number.isFinite(Number(content.height)) ? Math.max(0, Number(content.height)) : 0,
viewportHeight,
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
_restoreIndexSearchAnchor() {
// Intentionally no-op: native scroll anchoring is more stable than pageScrollTo here.
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
const oldHeight = anchor && anchor.resultsHeight > 0 ? anchor.resultsHeight : 0
const oldRetention = Math.max(0, Number(this._indexSearchRetentionHeight) || 0)
const oldFootprint = this._capIndexSearchFootprint(anchor, Math.max(oldHeight + oldRetention, Number(this._indexSearchFootprintHeight) || 0))
this._indexSearchFootprintHeight = oldFootprint
const leavingStyle = oldHeight > 0 ? `height:${oldHeight}px;overflow:hidden;` : ''
this.setData({
indexSearchPending: true,
indexResultsTransitioning: true,
indexResultsPhase: 'leaving',
indexResultsHeightStyle: leavingStyle,
}, () => {
const commit = () => {
if (this._unloaded || token !== this._indexSearchTransitionToken) return
this._indexLimit = INITIAL_INDEX_LIMIT
this.setData({ indexQuery: nextQuery }, () => {
this._applyIndexViewOnly(() => {
if (this._unloaded || token !== this._indexSearchTransitionToken) return
this._restoreIndexSearchAnchor(anchor)
this._measureIndexResultsHeight((newHeight) => {
if (this._unloaded || token !== this._indexSearchTransitionToken) return
const measuredNewHeight = Math.max(0, Number(newHeight) || 0)
const nextFootprint = Math.max(oldFootprint, measuredNewHeight)
this._indexSearchFootprintHeight = nextFootprint
const retentionPatch = this._indexSearchRetentionPatch(Math.max(0, nextFootprint - measuredNewHeight))
const heightStyle = oldHeight > 0 && measuredNewHeight > 0 ? `height:${measuredNewHeight}px;overflow:hidden;` : ''
const stillPending = normalizeSearchText(this.data.indexSearchDraft) !== normalizedNext
this.setData({
...retentionPatch,
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
const oldRetention = options.preserveIndexAnchor ? Math.max(0, Number(this._indexSearchRetentionHeight) || 0) : 0
const oldFootprint = options.preserveIndexAnchor
? this._capIndexSearchFootprint(anchor, Math.max(oldHeight + oldRetention, Number(this._indexSearchFootprintHeight) || 0))
: oldHeight
if (options.preserveIndexAnchor) this._indexSearchFootprintHeight = oldFootprint
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
indexScopeGroupKey: '',
themeSheetOpen: false,
themeSheetClosing: false,
themeSheetPendingKey: '__idle__',
themeQuery: '',
}, () => {
this.applyView(false, false, () => {
if (this._unloaded || token !== this._indexSearchTransitionToken) return
this._restoreIndexSearchAnchor(anchor)
this._measureIndexResultsHeight((newHeight) => {
if (this._unloaded || token !== this._indexSearchTransitionToken) return
const measuredNewHeight = Math.max(0, Number(newHeight) || 0)
const targetHeight = measuredNewHeight > 0 ? measuredNewHeight : oldHeight
const retentionPatch = options.preserveIndexAnchor
? this._indexSearchRetentionPatch(Math.max(0, Math.max(oldFootprint, targetHeight) - targetHeight))
: {}
if (options.preserveIndexAnchor) this._indexSearchFootprintHeight = Math.max(oldFootprint, targetHeight)
const heightStyle = oldHeight > 0 && targetHeight > 0 ? `height:${targetHeight}px;overflow:hidden;` : ''
const stillPending = normalizeSearchText(this.data.searchDraft) !== normalizedNext
this.setData({
...retentionPatch,
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
this.setData({ filter: 'all', query: '', searchDraft: '', searchPending: false, activeGroupKey: '', indexScopeGroupKey: '', themeSheetOpen: false, themeSheetClosing: false, themeSheetPendingKey: '__idle__', themeQuery: '' }, () => this.applyView(true))
},
chooseGroup(event) { this.openGroup(String(event.currentTarget.dataset.key || '')) },
rememberGroup(key) {
const normalized = String(key || '')
if (!normalized) return
const next = [normalized].concat(Array.isArray(this._recentGroupKeys) ? this._recentGroupKeys : [])
.filter((item, index, list) => item && list.indexOf(item) === index)
.slice(0, RECENT_THEME_LIMIT)
this._recentGroupKeys = next
try { if (this._recentGroupStorageKey) wx.setStorageSync(this._recentGroupStorageKey, next) } catch (error) { }
},
openGroup(key, callback) {
const normalized = String(key || '')
const targetGroup = normalized
? (this._filteredGroups || []).find(group => String(group.key) === normalized && group.matchCount > 0 && group.nodes.length)
: null
if (normalized && !targetGroup) { if (typeof callback === 'function') callback(); return }
if (targetGroup && targetGroup.rootNode && !targetGroup.rootNode.hasChildren) {
this.locatePointById(Number(targetGroup.rootId), { afterRender: callback, syncIndexScope: true })
return
}
const targetFocusId = targetGroup ? Number(targetGroup.rootId) || 0 : 0
if (normalized === this.data.activeGroupKey && Number(this._focusNodeId) === targetFocusId) { if (typeof callback === 'function') callback(); return }
this._graphPage = 0; this._indexLimit = INITIAL_INDEX_LIMIT; this._selectedId = 0
this._focusNodeId = targetFocusId
if (targetFocusId) this._expandedNodeIds.add(targetFocusId)
if (normalized) this.rememberGroup(normalized)
const quickGroupChips = buildQuickGroupChips(this.data.groupChips, normalized, this._recentGroupKeys)
this.transitionLabelView({ activeGroupKey: normalized, indexScopeGroupKey: normalized, quickGroupChips }, callback)
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
this.transitionLabelView({ activeGroupKey: normalizedGroupKey, indexScopeGroupKey: normalizedGroupKey, quickGroupChips }, callback)
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
this._selectedId = nextId
this._cancelIndexDetailReveal(true)
this.applyView(false, false)
},
_measureIndexDetailTarget(callback) {
if (typeof callback !== 'function') return
if (!wx.createSelectorQuery || this._unloaded || this._pageVisible === false) { callback(null); return }
try {
let query = wx.createSelectorQuery()
if (query.in) query = query.in(this)
query.select('#knowledge-point-detail-card').boundingClientRect()
query.select('#atlas-shell').boundingClientRect()
query.select('#knowledge-index-panel').boundingClientRect()
query.selectViewport().scrollOffset()
query.exec((result) => {
if (this._unloaded || this._pageVisible === false) { callback(null); return }
const detailRect = result && result[0]
const graphRect = result && result[1]
const indexRect = result && result[2]
const viewport = result && result[3]
let top = null
if (detailRect && Number.isFinite(Number(detailRect.top))) {
top = Number(detailRect.top)
} else if (graphRect && Number.isFinite(Number(graphRect.bottom))) {
let width = 375
try {
const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
width = Number(info && info.windowWidth) || width
} catch (error) { }
// The card is inserted immediately after the graph. Measure that future
// document position before rendering it, so the scroll target cannot jump.
top = Number(graphRect.bottom) + (18 * width / 750)
} else if (indexRect && Number.isFinite(Number(indexRect.top))) {
top = Number(indexRect.top)
}
if (top == null) { callback(null); return }
callback({
top,
scrollTop: viewport && Number.isFinite(Number(viewport.scrollTop)) ? Number(viewport.scrollTop) : (Number(this._scrollTop) || 0),
})
})
} catch (error) { callback(null) }
},
_scrollToIndexDetailTarget(callback) {
const done = typeof callback === 'function' ? callback : () => {}
if (this._unloaded || this._pageVisible === false) { done(false); return }
const token = (this._indexDetailScrollToken || 0) + 1
this._indexDetailScrollToken = token
this._measureIndexDetailTarget((layout) => {
if (this._unloaded || this._pageVisible === false || token !== this._indexDetailScrollToken) { done(false); return }
if (!layout || typeof wx.pageScrollTo !== 'function') { done(true); return }
const targetScrollTop = Math.max(0, Number(layout.scrollTop) + Number(layout.top) - INDEX_DETAIL_SCROLL_TOP_GAP)
if (Math.abs(targetScrollTop - Number(layout.scrollTop || 0)) < 1) {
done(true)
return
}
wx.pageScrollTo({
scrollTop: targetScrollTop,
duration: INDEX_DETAIL_SCROLL_MS,
complete: () => {
if (this._unloaded || this._pageVisible === false || token !== this._indexDetailScrollToken) { done(false); return }
this._scrollTop = targetScrollTop
done(true)
},
})
})
},
_cancelIndexDetailReveal(resetVisual = false) {
this._indexDetailRevealToken = (this._indexDetailRevealToken || 0) + 1
clearTimeout(this._indexDetailRevealTimer)
this._indexDetailRevealTimer = null
if (resetVisual && (this.data.indexDetailRevealPhase || this.data.indexDetailRevealStyle)) {
this.setData({ indexDetailRevealPhase: '', indexDetailRevealStyle: '' })
}
},
_prepareIndexDetailReveal(callback) {
this._cancelIndexDetailReveal(false)
const token = this._indexDetailRevealToken
const hadCard = Boolean(this.data.selectedPoint)
this._indexDetailRevealHadCard = hadCard
const patch = hadCard
? { indexDetailRevealPhase: 'holding', indexDetailRevealStyle: '' }
: { indexDetailRevealPhase: 'collapsed', indexDetailRevealStyle: 'height:0px;margin-top:0px;opacity:0;overflow:hidden;' }
this.setData(patch, () => {
if (typeof callback === 'function' && !this._unloaded && this._pageVisible !== false && token === this._indexDetailRevealToken) callback(token)
})
},
_expandIndexDetailCard(token, callback) {
const done = typeof callback === 'function' ? callback : () => {}
if (this._unloaded || this._pageVisible === false || token !== this._indexDetailRevealToken) { done(false); return }
if (this._indexDetailRevealHadCard) {
this._indexDetailRevealHadCard = false
this.setData({ indexDetailRevealPhase: 'settling', indexDetailRevealStyle: '' }, () => {
clearTimeout(this._indexDetailRevealTimer)
this._indexDetailRevealTimer = setTimeout(() => {
this._indexDetailRevealTimer = null
if (this._unloaded || this._pageVisible === false || token !== this._indexDetailRevealToken) { done(false); return }
this.setData({ indexDetailRevealPhase: '', indexDetailRevealStyle: '' }, () => done(true))
}, INDEX_DETAIL_REVEAL_MS)
})
return
}
const measure = () => {
if (this._unloaded || this._pageVisible === false || token !== this._indexDetailRevealToken) { done(false); return }
if (!wx.createSelectorQuery) {
this.setData({ indexDetailRevealPhase: '', indexDetailRevealStyle: '' }, () => done(true))
return
}
try {
let query = wx.createSelectorQuery()
if (query.in) query = query.in(this)
query.select('#knowledge-point-detail-card').boundingClientRect()
query.exec((result) => {
if (this._unloaded || this._pageVisible === false || token !== this._indexDetailRevealToken) { done(false); return }
const rect = result && result[0]
const height = rect && Number.isFinite(Number(rect.height)) ? Math.max(1, Math.ceil(Number(rect.height))) : 0
if (!height) {
this.setData({ indexDetailRevealPhase: '', indexDetailRevealStyle: '' }, () => done(true))
return
}
let width = 375
try {
const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
width = Number(info && info.windowWidth) || width
} catch (error) { }
const gap = Math.max(0, 18 * width / 750)
this.setData({
indexDetailRevealPhase: 'expanding',
indexDetailRevealStyle: `height:${height}px;margin-top:${gap}px;opacity:1;overflow:hidden;`,
}, () => {
clearTimeout(this._indexDetailRevealTimer)
this._indexDetailRevealTimer = setTimeout(() => {
this._indexDetailRevealTimer = null
if (this._unloaded || this._pageVisible === false || token !== this._indexDetailRevealToken) { done(false); return }
this.setData({ indexDetailRevealPhase: '', indexDetailRevealStyle: '' }, () => done(true))
}, INDEX_DETAIL_REVEAL_MS)
})
})
} catch (error) {
this.setData({ indexDetailRevealPhase: '', indexDetailRevealStyle: '' }, () => done(true))
}
}
if (typeof wx.nextTick === 'function') wx.nextTick(measure)
else setTimeout(measure, 0)
},
_finishIndexNavigation(pointId) {
if (this._unloaded || this._pageVisible === false) return
if (Number(this.data.indexNavigatingId) === Number(pointId)) this.setData({ indexNavigatingId: 0 })
},
_runIndexInteraction(id) {
const pointId = Number(id)
if (!pointId || Number(this.data.indexNavigatingId)) return
const dedicatedQuery = normalizeSearchText(this.data.indexQuery)
const row = (Array.isArray(this.data.indexNodes) ? this.data.indexNodes : []).find(item => Number(item.knowledge_point_id) === pointId)
if (!dedicatedQuery && row && row.indexExpandable && !row.indexForcedOpen) {
this.activateIndexNode(pointId)
return
}
if (dedicatedQuery) {
if (!row || !row.matched) return
this._navigateFromIndexSearch(pointId)
return
}
if (row && row.hasChildren) {
this.activateIndexNode(pointId, { keepViewport: true })
return
}
// Scroll to the future card position first. The card is then mounted inside a
// zero-height shell and expanded to its measured height, so the index below is
// pushed down progressively instead of jumping when selectedPoint appears.
this.setData({ indexNavigatingId: pointId }, () => {
this._scrollToIndexDetailTarget((ready) => {
if (!ready || this._unloaded || this._pageVisible === false) { this._finishIndexNavigation(pointId); return }
this._prepareIndexDetailReveal((revealToken) => {
this.activateIndexNode(pointId, {
keepViewport: true,
afterRender: () => this._expandIndexDetailCard(revealToken, () => this._finishIndexNavigation(pointId)),
})
})
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
try { wx.hideKeyboard() } catch (error) { }
}
this.setData({ indexNavigatingId: pointId, indexSearchFocused: false, searchFocused: false })
this._indexNavigateTimer = setTimeout(() => {
this._indexNavigateTimer = null
if (this._unloaded || this._pageVisible === false) return
this._scrollToIndexDetailTarget((ready) => {
if (!ready || this._unloaded || this._pageVisible === false) { this._finishIndexNavigation(pointId); return }
this._prepareIndexDetailReveal((revealToken) => {
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
// Avoid graph entrance animation while landing on the detail card; the graph is
// outside the focal viewport and the extra compositor pass can look like a flash.
this.applyView(true, false, () => this._expandIndexDetailCard(revealToken, () => this._finishIndexNavigation(pointId)))
})
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
this._applyIndexViewOnly(done)
return
}
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
}
const parentId = Number(point.parentId) || 0
if (parentId) {
const siblings = group.nodes.filter(item => Number(item.parentId) === parentId)
const index = siblings.findIndex(item => Number(item.knowledge_point_id) === Number(point.knowledge_point_id))
if (index < 0) { finish(); return }
this._focusNodeId = parentId
this._graphPage = Math.floor(index / POINTS_PER_PAGE)
const nextData = { activeGroupKey: String(point.groupKey) }
if (options.syncIndexScope) nextData.indexScopeGroupKey = String(point.groupKey)
this.setData(nextData, () => this.applyView(true, options.scrollToGraph !== false, finish))
} else {
const availableGroups = (this._filteredGroups || []).filter(item => item.matchCount > 0 && item.nodes.length)
const groupIndex = availableGroups.findIndex(item => String(item.key) === String(point.groupKey))
if (groupIndex < 0) { finish(); return }
this._focusNodeId = 0
this._graphPage = Math.floor(groupIndex / POINTS_PER_PAGE)
const nextData = { activeGroupKey: '' }
if (options.syncIndexScope) nextData.indexScopeGroupKey = ''
this.setData(nextData, () => this.applyView(true, options.scrollToGraph !== false, finish))
}
},
loadMore() { this._indexLimit = (this._indexLimit || INITIAL_INDEX_LIMIT) + INITIAL_INDEX_LIMIT; this._applyIndexViewOnly() },
openPoint(event) {
const id = Number(event.currentTarget.dataset.id)
if (!id || this._detailNavigationPending || this._practiceNavigationPending) return
const state = this._captureViewState()
this._pendingReturnState = state
this._persistViewState(state)
this._detailNavigationPending = true
wx.navigateTo({
url: `/subpackages/knowledge/knowledge-detail/index?knowledge_point_id=${id}`,
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
const returnTo = encodeURIComponent(`/subpackages/knowledge/knowledge-subject/index?subject_id=${this.subjectId}&restore_state=1`)
const subjectName = encodeURIComponent(String((this.data.subject && this.data.subject.subject_name) || item.groupName || '专项练习'))
const url = `/subpackages/study/practice/practice?subject_id=${this.subjectId}&subject_name=${subjectName}&mode=random&count=${count}&knowledge_point_id=${item.knowledge_point_id}&include_children=1&allow_repeat=1&autostart=1&source=knowledge_map&return_to=${returnTo}`
this._practiceNavigationPending = true
this._refreshAfterReturn = true
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
if (!rect || !rect.width || this._unloaded || this._pageVisible === false) return
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
if (this._unloaded || this._pageVisible === false || !this._frame || !this._camera) return
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

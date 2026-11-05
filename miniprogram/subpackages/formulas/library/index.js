const api = require('../../../utils/api')
const auth = require('../../../utils/auth')
const loginGate = require('../../../utils/login-gate')
const formulaContent = require('../utils/formula-content')
const Parser = require('../utils/mp-html-parser')
const LatexPlugin = require('../utils/katex/index')
const { resolveGraphImageUrl, resolveGraphThumbnailUrl, resolveGraphPreviewUrl } = require('../utils/formula-graph')
const { parseServerUtc, getChinaWallParts } = require('../../../utils/china-time')

function formulaNowMs() {
  const synced = api && typeof api.now === 'function' ? Number(api.now()) : NaN
  return Number.isFinite(synced) ? synced : Date.now()
}

function formatChinaDateTime(value) {
  const ms = typeof value === 'number' ? value : parseServerUtc(value)
  if (!Number.isFinite(ms)) return ''
  const p = getChinaWallParts(ms)
  const pad = (n) => String(n).padStart(2, '0')
  return `${p.year}-${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}`
}

function renderFormulaTitleNodes(title) {
  const source = formulaContent.normalizeMixedContent(title)
  if (!source) return []

  try {
    const host = {
      properties: {
        editable: false,
        containerStyle: '',
        mathLayout: 'natural',
      },
      imgList: [],
      plugins: [new LatexPlugin()],
    }
    return new Parser(host).parse(source)
  } catch (error) {
    console.warn('Formula library title render failed, falling back to plain text', error)
    return [{ type: 'text', text: String(title || '') }]
  }
}

const READER_SEQUENCE_KEY = 'formula_reader_sequence_v2'
const SEARCH_DEBOUNCE_MS = 500
const LIBRARY_TYPE_FORMULA = 'formula'
const LIBRARY_TYPE_FUNCTION_GRAPH = 'function_graph'
const MAX_GRAPH_FALLBACK_PAGES = 10
const MAX_FAVORITE_PAGES = 50
const FAVORITE_PAGE_SIZE = 200

const MATH_FORMULA_SUBJECT = 'math'
const BASE_FORMULA_SUBJECTS = [
  { code: MATH_FORMULA_SUBJECT, name: '数学' },
  { code: 'math2_linear_algebra', name: '线性代数' },
  { code: 'exam408', name: '计算机综合' },
]
const DEFAULT_FORMULA_SUBJECT = MATH_FORMULA_SUBJECT
const EXAM408_FORMULA_SUBJECT = 'exam408'
const HIDDEN_FORMULA_SUBJECT_CODES = new Set(['elementary_math', 'math2_high_math'])

function isVisibleFormulaSubject(subject) {
  const code = String(subject && (subject.code || subject.subject_code || subject.key) || '').trim().toLowerCase()
  const name = String(subject && (subject.name || subject.title || subject.label || subject.subject_name) || '').trim()
  return !HIDDEN_FORMULA_SUBJECT_CODES.has(code) && name !== '初等数学' && name !== '高等数学'
}

function mergeFormulaSubjects(catalog, activeCode) {
  const merged = []
  const seen = Object.create(null)
  BASE_FORMULA_SUBJECTS.forEach(function (subject) {
    merged.push({
      code: subject.code,
      name: subject.name,
      active: subject.code === activeCode,
    })
    seen[subject.code] = true
  })
  ;(catalog || []).forEach(function (subject) {
    if (!isVisibleFormulaSubject(subject)) return
    const code = String(subject && subject.code || '').trim()
    if (!code || seen[code]) return
    merged.push({
      code,
      name: subject.name || code,
      active: code === activeCode,
    })
    seen[code] = true
  })
  return merged
}

const STUDY_CARD_TYPES = [
  { key: '', name: '全部' },
  { key: 'formula', name: '公式' },
  { key: 'definition', name: '定义' },
  { key: 'complexity', name: '复杂度' },
  { key: 'protocol_rule', name: '协议规则' },
  { key: 'key_conclusion', name: '高频结论' },
  { key: 'confusable', name: '易混' },
  { key: 'trap', name: '陷阱' },
  { key: 'comparison', name: '对比' },
]
const STUDY_CARD_TYPE_LABEL = STUDY_CARD_TYPES.reduce(function (acc, item) {
  if (item.key) acc[item.key] = item.name
  return acc
}, {})

function getStudyCardTypeLabel(item) {
  var key = String(item?.study_card_type || item?.studyCardType || 'formula').trim().toLowerCase()
  return STUDY_CARD_TYPE_LABEL[key] || '速记'
}

function normalizeCardType(item) {
  return String(
    item?.card_type ||
    item?.cardType ||
    item?.content_type ||
    item?.contentType ||
    ''
  ).trim().toLowerCase()
}

function hasGraphAsset(item) {
  const graphAsset = item?.graph_asset || item?.graphAsset
  if (typeof graphAsset === 'string') return Boolean(graphAsset.trim())
  if (graphAsset && typeof graphAsset === 'object' && Object.keys(graphAsset).length > 0) return true
  return Boolean(resolveGraphImageUrl(item) || resolveGraphThumbnailUrl(item))
}

function isFunctionGraphItem(item) {
  const cardType = normalizeCardType(item)
  if (cardType === LIBRARY_TYPE_FUNCTION_GRAPH) return true
  if (cardType === 'pure_formula') return false
  return hasGraphAsset(item)
}

function filterFormulaItemsByLibraryType(items, libraryType) {
  if (libraryType !== LIBRARY_TYPE_FUNCTION_GRAPH) return items || []
  return (items || []).filter((item) => item.isFunctionGraph || isFunctionGraphItem(item))
}

Page({
  data: {
    // Subject tabs
    subjects: BASE_FORMULA_SUBJECTS.map(function (subject) {
      return { ...subject, active: subject.code === DEFAULT_FORMULA_SUBJECT }
    }),
    activeSubject: DEFAULT_FORMULA_SUBJECT,
    activeSubjectName: '数学',

    // Content type tabs
    libraryTabs: [
      { key: LIBRARY_TYPE_FORMULA, name: '公式', active: true },
      { key: LIBRARY_TYPE_FUNCTION_GRAPH, name: '函数图像', active: false },
    ],
    activeLibraryType: LIBRARY_TYPE_FORMULA,

    // Memory-card semantic type
    studyTypeTabs: STUDY_CARD_TYPES.map(function (item) { return { ...item, active: !item.key } }),
    activeStudyCardType: '',

    // Catalog tree
    catalog: [],
    chapters: [],
    activeChapterId: null,

    // Tags
    tags: [],
    activeTags: [],
    _shownActiveTags: [],

    // Search
    searchValue: '',

    // Favorites
    onlyFavorites: false,
    favoriteIds: [],

    // List
    formulas: [],
    page: 1,
    pageSize: 20,
    total: 0,
    hasMore: true,

    // UI state
    navHeight: 88,
    showChapterPicker: false,
    showTagPicker: false,
    showSubjectPicker: false,
    showMoreSheet: false,

    // Loading states
    initialLoading: true,
    loadingMore: false,
    loadError: false,
    loadErrorMessage: '',
  },


  _pageAlive: true,
  _visible: true,
  _catalogRequestVersion: 0,
  _tagsRequestVersion: 0,
  _favoriteRequestVersion: 0,
  _replaceRequestVersion: 0,
  _favoriteBusyIds: null,

  onLoad(options = {}) {
    this._pageAlive = true
    this._visible = true
    this._favoriteBusyIds = new Set()
    this.measureNavigation()
    const onlyFavorites = options.favorites === '1'
    if (onlyFavorites) this.setData({ onlyFavorites: true })
    this.loadCatalog()
    this.loadTags()
    this.loadFavoriteIds()
    this.loadFormulas(true)
  },

  onShow() {
    this._visible = true
    // onLoad already performs the initial request. Refresh favorites every time
    // the page becomes visible again so a toggle made in the reader is reflected
    // immediately when the user navigates back to the library.
    if (!this._hasShownOnce) {
      this._hasShownOnce = true
      return
    }
    this.loadFavoriteIds()
  },


  measureNavigation() {
    let statusBarHeight = 20
    try {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
      statusBarHeight = Number(info.statusBarHeight || 20)
    } catch (_) {}

    let menu = null
    try {
      menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect()
    } catch (_) {}

    const menuTop = menu && menu.top ? Number(menu.top) : statusBarHeight + 6
    const menuHeight = menu && menu.height ? Number(menu.height) : 32
    const verticalGap = Math.max(4, menuTop - statusBarHeight)
    this.setData({ navHeight: statusBarHeight + menuHeight + verticalGap * 2 })
  },

  onPullDownRefresh() {
    this.setData({ page: 1, formulas: [], hasMore: true })
    this.loadFormulas(true)
      .then(() => wx.stopPullDownRefresh())
      .catch(() => wx.stopPullDownRefresh())
  },

  // ── Catalog ──

  async loadCatalog() {
    if (!this._pageAlive) return
    const requestVersion = ++this._catalogRequestVersion
    try {
      var params = {}
      // Ask the backend for the selected subject's catalog. For math this
      // returns the logical root that combines elementary and high math.
      if (this.data.activeSubject === MATH_FORMULA_SUBJECT) params.subject_code = MATH_FORMULA_SUBJECT
      // Keep the 408 catalog explicitly scoped. exam_scope prevents unrelated
      // formula trees from influencing 408 counts while filters are applied.
      if (this.data.activeSubject === EXAM408_FORMULA_SUBJECT) params.exam_scope = EXAM408_FORMULA_SUBJECT
      // Pass library_type so the catalog can show accurate available_count
      if (this.data.activeLibraryType && this.data.activeLibraryType !== LIBRARY_TYPE_FORMULA) {
        params.library_type = this.data.activeLibraryType
      }
      if (this.data.activeSubject === EXAM408_FORMULA_SUBJECT && this.data.activeStudyCardType) params.study_card_type = this.data.activeStudyCardType
      if (typeof this.data.onlyFavorites !== 'undefined' && this.data.onlyFavorites) {
        params.favorite_only = true
      }
      var url = '/formulas/catalog'
      if (Object.keys(params).length) {
        url += '?' + Object.keys(params).map(function(k) { return k + '=' + encodeURIComponent(params[k]) }).join('&')
      }
      const data = await api.request('GET', url, {}, { auth: 'optional' })
      if (!this._pageAlive || requestVersion !== this._catalogRequestVersion) return
      const catalog = this.normalizeCatalog(data?.items || [])
      const currentCode = this.data.activeSubject || DEFAULT_FORMULA_SUBJECT
      const allCodes = BASE_FORMULA_SUBJECTS.map(function (subject) { return subject.code })
        .concat(catalog.map(function (subject) { return subject.code }))
      const activeSubject = allCodes.indexOf(currentCode) >= 0
        ? currentCode
        : DEFAULT_FORMULA_SUBJECT
      const subjects = mergeFormulaSubjects(catalog, activeSubject)
      const activeMeta = subjects.find(function (subject) { return subject.code === activeSubject })
      const subjectChanged = activeSubject !== currentCode
      this.setData({
        catalog,
        subjects,
        activeSubject,
        activeSubjectName: activeMeta ? activeMeta.name : '数学',
      }, () => {
        this.updateChapters()
        if (subjectChanged) this.loadFormulas(true)
      })
    } catch (e) {
      if (!this._pageAlive || requestVersion !== this._catalogRequestVersion) return
      console.error('Failed to load formula catalog', e)
    }
  },


  normalizeCatalog(items = []) {
    return (items || []).filter(isVisibleFormulaSubject).map((subject, subjectIndex) => {
      const rawChildren = subject.children || subject.chapters || subject.items || []
      const children = (rawChildren || [])
        .map((chapter, chapterIndex) => ({
          ...chapter,
          id: chapter.id || chapter.chapter_id || chapter.catalog_id || chapter.code || `${subjectIndex + 1}-${chapterIndex + 1}`, 
          name: chapter.name || chapter.title || chapter.label || chapter.chapter_name || `第${chapterIndex + 1}章`,
        }))
        .filter((chapter) => chapter.name)

      return {
        ...subject,
        code: subject.code || subject.subject_code || subject.key || '',
        name: subject.name || subject.title || subject.label || subject.subject_name || `科目${subjectIndex + 1}`,
        children,
      }
    })
  },

  async loadTags() {
    if (!this._pageAlive) return
    const requestVersion = ++this._tagsRequestVersion
    try {
      const data = await api.request('GET', '/formulas/tags', {}, { auth: 'optional' })
      if (!this._pageAlive || requestVersion !== this._tagsRequestVersion) return
      this.setData({ tags: data?.items || [] }, () => {
        this._syncTagFlags()
      })
    } catch (e) {
      if (!this._pageAlive || requestVersion !== this._tagsRequestVersion) return
      console.error('Failed to load formula tags', e)
    }
  },

  _syncTagFlags() {
    const { tags, activeTags } = this.data
    var activeMap = {}
    for (var i = 0; i < activeTags.length; i++) {
      activeMap[activeTags[i]] = true
    }
    var shown = []
    for (var j = 0; j < tags.length; j++) {
      var t = tags[j]
      t._active = !!activeMap[t.id]
      if (t._active) shown.push(t)
    }
    this.setData({
      tags: tags.slice(),
      _shownActiveTags: shown,
    })
  },

  updateChapters() {
    // Find the currently active subject in catalog. Preserve the selected
    // chapter when a catalog refresh (for example favorite-only) still contains
    // it; silently resetting it would desynchronise the filters and the list.
    const { catalog, activeSubject, activeChapterId } = this.data
    const subject = catalog.find(s => s.code === activeSubject)
    if (subject) {
      const chapters = (subject.children || []).map((chapter) => ({
        ...chapter,
        active: activeChapterId != null && String(chapter.id) === String(activeChapterId),
        available_count: chapter.available_count || 0,
      }))
      const keepActiveChapter = activeChapterId != null && chapters.some(
        (chapter) => String(chapter.id) === String(activeChapterId)
      )
      this.setData({
        chapters,
        activeChapterId: keepActiveChapter ? activeChapterId : null,
      })
    } else {
      this.setData({ chapters: [], activeChapterId: null })
    }
  },

  // ── Subject Switch ──

  onSubjectChange(e) {
    const code = e.currentTarget.dataset.code
    const selectedSubject = (this.data.subjects || []).find((subject) => subject.code === code)
    if (code === this.data.activeSubject) {
      this.setData({ showSubjectPicker: false })
      return
    }
    const subjects = this.data.subjects.map(s => ({
      ...s, active: s.code === code,
    }))
    const keepStudyType = code === EXAM408_FORMULA_SUBJECT
    this.setData({
      subjects,
      activeSubject: code,
      activeSubjectName: selectedSubject?.name || '选择学科',
      activeChapterId: null,
      activeTags: [],
      searchValue: '',
      onlyFavorites: false,
      favoriteIds: [],
      activeStudyCardType: keepStudyType ? this.data.activeStudyCardType : '',
      studyTypeTabs: keepStudyType
        ? this.data.studyTypeTabs
        : STUDY_CARD_TYPES.map(function (item) { return { ...item, active: !item.key } }),
      page: 1,
      formulas: [],
      hasMore: true,
      showSubjectPicker: false,
      showMoreSheet: false,
    })
    this._syncTagFlags()
    this.loadCatalog()
    this.loadFormulas(true)
  },

  toggleSubjectPicker() {
    this.setData({
      showSubjectPicker: !this.data.showSubjectPicker,
      showMoreSheet: false,
      showTagPicker: false,
    })
  },

  toggleMoreSheet() {
    this.setData({
      showMoreSheet: !this.data.showMoreSheet,
      showSubjectPicker: false,
      showTagPicker: false,
    })
  },

  openTagPickerFromMore() {
    this.setData({
      showMoreSheet: false,
      showTagPicker: true,
      showSubjectPicker: false,
    })
  },

  resetFilters() {
    const hasActiveFilters = Boolean(
      this.data.searchValue ||
      this.data.activeChapterId ||
      (this.data.activeTags || []).length ||
      this.data.onlyFavorites ||
      this.data.activeStudyCardType
    )
    if (!hasActiveFilters) {
      this.setData({ showMoreSheet: false })
      return
    }
    if (this._searchTimer) clearTimeout(this._searchTimer)
    this._searchTimer = null
    const chapters = (this.data.chapters || []).map((chapter) => ({ ...chapter, active: false }))
    this.setData({
      chapters,
      activeChapterId: null,
      activeTags: [],
      searchValue: '',
      onlyFavorites: false,
      activeStudyCardType: '',
      studyTypeTabs: STUDY_CARD_TYPES.map(function (item) { return { ...item, active: !item.key } }),
      page: 1,
      formulas: [],
      total: 0,
      hasMore: true,
      showMoreSheet: false,
      showTagPicker: false,
    })
    this._syncTagFlags()
    this.loadFormulas(true)
  },

  // ── Content Type Switch ──

  onLibraryTypeChange(e) {
    const type = e.currentTarget.dataset.type
    if (!type || type === this.data.activeLibraryType) return
    const libraryTabs = (this.data.libraryTabs || []).map((tab) => ({
      ...tab,
      active: tab.key === type,
    }))
    this.setData({
      libraryTabs,
      activeLibraryType: type,
      page: 1,
      formulas: [],
      total: 0,
      hasMore: true,
      loadError: false,
      showChapterPicker: false,
      showTagPicker: false,
      showSubjectPicker: false,
      showMoreSheet: false,
    })
    this.loadCatalog()
    this.loadFormulas(true)
  },

  // ── Study Card Type ──

  onStudyCardTypeChange(e) {
    if (this.data.activeSubject !== EXAM408_FORMULA_SUBJECT) return
    const type = String(e.currentTarget.dataset.type || '')
    if (type === this.data.activeStudyCardType) return
    const studyTypeTabs = (this.data.studyTypeTabs || []).map((tab) => ({ ...tab, active: tab.key === type }))
    this.setData({
      studyTypeTabs,
      activeStudyCardType: type,
      page: 1,
      formulas: [],
      total: 0,
      hasMore: true,
      loadError: false,
    })
    this.loadCatalog()
    this.loadFormulas(true)
  },

  // ── Chapter Filter ──

  toggleChapterPicker() {
    this.setData({ showChapterPicker: !this.data.showChapterPicker })
  },

  onChapterSelect(e) {
    var rawId = e.currentTarget.dataset.id
    // Normalize to number; "全部章节" (0, '0', '') becomes null
    var chapterId = null
    if (rawId !== 0 && rawId !== '0' && rawId !== '' && rawId !== null && rawId !== undefined) {
      chapterId = Number(rawId)
      if (isNaN(chapterId)) chapterId = null
    }
    const isCurrent = chapterId != null && chapterId === this.data.activeChapterId
    const nextChapterId = isCurrent ? null : chapterId
    const chapters = (this.data.chapters || []).map((chapter) => ({
      ...chapter,
      active: nextChapterId != null && chapter.id === nextChapterId,
    }))

    this.setData({
      chapters,
      activeChapterId: nextChapterId,
      showChapterPicker: false,
      page: 1,
      formulas: [],
      hasMore: true,
      total: 0,
      loadError: false,
    }, function () {
      this.loadFormulas(true)
    })
  },

  // ── Tag Filter ──

  toggleTagPicker() {
    this.setData({
      showTagPicker: !this.data.showTagPicker,
      showChapterPicker: false,
      showSubjectPicker: false,
      showMoreSheet: false,
    })
  },

  onTagSelect(e) {
    const tagId = e.currentTarget.dataset.id
    let activeTags = (this.data.activeTags || []).slice()
    const idx = activeTags.indexOf(tagId)
    if (idx >= 0) {
      activeTags.splice(idx, 1)
    } else {
      activeTags.push(tagId)
    }
    this.setData({
      activeTags,
      page: 1,
      formulas: [],
      hasMore: true,
    })
    this._syncTagFlags()
    this.loadFormulas(true)
  },

  // ── Search ──

  onSearchInput(e) {
    const value = e.detail.value || ''
    this.setData({ searchValue: value })
    if (this._searchTimer) clearTimeout(this._searchTimer)
    this._searchTimer = setTimeout(() => {
      this._searchTimer = null
      this.applySearch(value)
    }, SEARCH_DEBOUNCE_MS)
  },

  onSearchConfirm(e) {
    const value = (e.detail && e.detail.value) || this.data.searchValue || ''
    if (this._searchTimer) clearTimeout(this._searchTimer)
    this._searchTimer = null
    this.setData({ searchValue: value })
    this.applySearch(value)
  },

  applySearch(value) {
    // Ignore a timer that belongs to an older input value.
    if (String(value || '') !== String(this.data.searchValue || '')) return
    this.setData({ page: 1, formulas: [], hasMore: true })
    this.loadFormulas(true)
  },

  onSearchClear() {
    if (this._searchTimer) clearTimeout(this._searchTimer)
    this._searchTimer = null
    this.setData({ searchValue: '', page: 1, formulas: [], hasMore: true })
    this.loadFormulas(true)
  },

  onHide() {
    this._visible = false
  },

  onUnload() {
    this._pageAlive = false
    this._visible = false
    this._catalogRequestVersion++
    this._tagsRequestVersion++
    this._favoriteRequestVersion++
    this._replaceRequestVersion++
    if (this._searchTimer) clearTimeout(this._searchTimer)
    this._searchTimer = null
    if (this._favoriteBusyIds) this._favoriteBusyIds.clear()
  },

  // ── Favorites toggle ──

  toggleFavoritesOnly() {
    this.setData({
      onlyFavorites: !this.data.onlyFavorites,
      page: 1,
      formulas: [],
      hasMore: true,
    })
    this.loadCatalog()
    this.loadFormulas(true)
  },

  // ── Load Formulas ──

  async loadFormulas(replace = false) {
    if (!this._pageAlive) return
    if (replace) this._replaceRequestVersion = (this._replaceRequestVersion || 0) + 1
    var requestVersion = this._replaceRequestVersion || 0
    var d = this.data
    if (d.loading || d.loadingMore || (d.initialLoading && !replace) || !d.hasMore) return
    var loadingFlag = replace ? "initialLoading" : "loadingMore"
    this.setData({ [loadingFlag]: true, loadError: false })
    try {
      var baseParams = this._buildFormulaParams(d)
      var fetchResult = await this._fetchFormulaPages(baseParams, d.pageSize, d.activeLibraryType)
      if (!this._pageAlive || requestVersion !== (this._replaceRequestVersion || 0)) return
      this.setData(this._buildFormulaResultPatch(fetchResult, d, replace, requestVersion))
    } catch (e) {
      this._handleFormulaLoadError(e, replace, requestVersion)
    }
  },

  _buildFormulaParams(d) {
    var params = {
      subject_code: d.activeSubject,
      page_size: d.pageSize,
      library_type: d.activeLibraryType || LIBRARY_TYPE_FORMULA,
    }
    if (d.activeSubject === EXAM408_FORMULA_SUBJECT) params.exam_scope = EXAM408_FORMULA_SUBJECT
    if (d.activeSubject === EXAM408_FORMULA_SUBJECT && d.activeStudyCardType) params.study_card_type = d.activeStudyCardType
    if (d.activeChapterId) params.chapter_id = d.activeChapterId
    if (d.activeTags.length) {
      var tagCodes = this.data.tags.filter(function(t) { return d.activeTags.includes(t.id) }).map(function(t) { return t.code }).join(",")
      if (tagCodes) params.tags = tagCodes
    }
    if (d.searchValue) params.q = d.searchValue
    if (d.onlyFavorites) params.favorite_only = true
    return params
  },

  async _fetchFormulaPages(baseParams, pageSize, activeLibraryType) {
    var requestPage = this.data.page, responseData = null, rawItems = [], items = [], attempts = 0
    do {
      responseData = await api.request(
        'GET', '/formulas', Object.assign({}, baseParams, { page: requestPage }),
        { auth: 'optional' },
      )
      rawItems = (responseData && responseData.items) || []
      var decorated = this.decorateFormulaItems(rawItems)
      items = filterFormulaItemsByLibraryType(decorated, activeLibraryType)
      requestPage += 1; attempts += 1
    } while (activeLibraryType === LIBRARY_TYPE_FUNCTION_GRAPH && items.length === 0 && rawItems.length === pageSize && attempts < MAX_GRAPH_FALLBACK_PAGES)
    return { responseData: responseData, rawItems: rawItems, items: items, requestPage: requestPage, pageSize: pageSize }
  },

  _buildFormulaResultPatch(fetchResult, d, replace, requestVersion) {
    var rawTotal = (fetchResult.responseData && (fetchResult.responseData.filtered_total != null ? fetchResult.responseData.filtered_total : fetchResult.responseData.total))
    var parsedTotal = Number(rawTotal)
    var hasKnownTotal = Number.isFinite(parsedTotal) && parsedTotal >= 0
    var mergedFormulas = replace ? fetchResult.items : (d.formulas || []).concat(fetchResult.items).filter(function(item, index, list) {
      return list.findIndex(function(candidate) { return String(candidate.id) === String(item.id) }) === index
    })
    var fetchedThroughPage = Math.max(0, fetchResult.requestPage - 1)
    var totalItems = hasKnownTotal ? parsedTotal : mergedFormulas.length
    var hasMoreByResponse = fetchResult.rawItems.length === fetchResult.pageSize
    return {
      formulas: mergedFormulas, total: totalItems, page: fetchResult.requestPage,
      hasMore: hasKnownTotal ? fetchedThroughPage * fetchResult.pageSize < totalItems : hasMoreByResponse,
      initialLoading: false, loadingMore: false,
    }
  },

  _handleFormulaLoadError(e, replace, requestVersion) {
    if (!this._pageAlive || requestVersion !== (this._replaceRequestVersion || 0)) return
    console.error("Failed to load formulas", e)
    var shouldReplaceWithError = replace || !(this.data.formulas || []).length
    this.setData({ initialLoading: false, loadingMore: false, loadError: shouldReplaceWithError, loadErrorMessage: shouldReplaceWithError ? (e.message || "加载失败") : "" })
    if (!shouldReplaceWithError) wx.showToast({ title: "加载更多失败，请重试", icon: "none" })
  },

  isFunctionGraphItem(item) {
    return isFunctionGraphItem(item)
  },

  filterFormulaItemsByLibraryType(items, libraryType) {
    return filterFormulaItemsByLibraryType(items, libraryType)
  },

  decorateFormulaItems(items) {
    const favoriteIds = this.data.favoriteIds || []
    return (items || []).map((item) => {
      const graphImageUrl = resolveGraphImageUrl(item)
      const graphThumbnailUrl = resolveGraphThumbnailUrl(item)
      const isFunctionGraph = isFunctionGraphItem(item)
      // List cards render at ~360rpx height; loading the full-size master
      // image there is the dominant source of slow graph rendering.
      const graphPreviewUrl = resolveGraphPreviewUrl(item)
      return {
        ...item,
        titleNodes: renderFormulaTitleNodes(item.title),
        graphImageUrl,
        graphThumbnailUrl,
        graphPreviewUrl,
        isFunctionGraph,
        studyCardTypeLabel: getStudyCardTypeLabel(item),
        // 速记业务时间统一按 Asia/Shanghai 展示；服务端无时区历史值
        // 由 china-time 按 UTC 解析，避免跟随开发者工具/手机本地时区。
        publishedAtChina: formatChinaDateTime(item.published_at || item.publishedAt),
        createdAtChina: formatChinaDateTime(item.created_at || item.createdAt),
        updatedAtChina: formatChinaDateTime(item.updated_at || item.updatedAt),
        graphLoadError: false,
        isFavorited: Boolean(item.isFavorited || item.is_favorited || favoriteIds.includes(Number(item.id))),
      }
    })
  },

  onGraphImageError(e) {
    const formulaId = e.currentTarget.dataset.id
    const formulas = (this.data.formulas || []).map((item) => (
      String(item.id) === String(formulaId)
        ? { ...item, graphLoadError: true }
        : item
    ))
    this.setData({ formulas })
  },

  async loadFavoriteIds() {
    if (!this._pageAlive || !auth.isLoggedIn()) return
    const requestVersion = ++this._favoriteRequestVersion
    try {
      const favoriteIds = []
      const favoriteIdSet = new Set()
      let page = 1
      let total = null

      while (page <= MAX_FAVORITE_PAGES) {
        const data = await api.request('GET', '/formulas/favorites/list', {
          page,
          page_size: FAVORITE_PAGE_SIZE,
        })
        if (!this._pageAlive || requestVersion !== this._favoriteRequestVersion) return

        const items = data?.items || []
        items.forEach((item) => {
          const id = Number(item.id)
          if (id && !favoriteIdSet.has(id)) {
            favoriteIdSet.add(id)
            favoriteIds.push(id)
          }
        })

        const parsedTotal = Number(data?.total)
        if (Number.isFinite(parsedTotal) && parsedTotal >= 0) total = parsedTotal
        if (items.length < FAVORITE_PAGE_SIZE) break
        if (total != null && favoriteIds.length >= total) break
        page += 1
      }

      if (!this._pageAlive || requestVersion !== this._favoriteRequestVersion) return
      const favoriteSet = new Set(favoriteIds)
      const formulas = (this.data.formulas || []).map((item) => {
        const isFavorited = favoriteSet.has(Number(item.id))
        return {
          ...item,
          isFavorited,
          is_favorited: isFavorited,
        }
      }).filter((item) => !this.data.onlyFavorites || item.isFavorited)
      this.setData({ favoriteIds, formulas })
    } catch (e) {
      if (!this._pageAlive || requestVersion !== this._favoriteRequestVersion) return
      console.warn('Failed to load formula favorites', e)
    }
  },

  async toggleFormulaFavorite(e) {
    if (!auth.isLoggedIn()) {
      loginGate.promptLogin({ content: '收藏公式需要登录。你仍然可以继续浏览其他公式。' })
      return
    }

    const formulaId = Number(e.currentTarget.dataset.id)
    if (!formulaId || !this._pageAlive) return
    if (!this._favoriteBusyIds) this._favoriteBusyIds = new Set()
    if (this._favoriteBusyIds.has(formulaId)) return

    const currentItem = (this.data.formulas || []).find((item) => Number(item.id) === formulaId)
    if (!currentItem) return
    const current = Boolean(currentItem.isFavorited || currentItem.is_favorited)
    this._favoriteBusyIds.add(formulaId)

    try {
      if (current) {
        await api.request('DELETE', `/formulas/${formulaId}/favorite`)
      } else {
        await api.request('PUT', `/formulas/${formulaId}/favorite`)
      }
      if (!this._pageAlive) return

      // Invalidate a favorite-list GET that may have started before this write;
      // an older response must not undo the user's latest toggle.
      this._favoriteRequestVersion++
      const isFavorited = !current
      let formulas = (this.data.formulas || []).map((item) => (
        Number(item.id) === formulaId
          ? { ...item, isFavorited, is_favorited: isFavorited }
          : item
      ))
      const favoriteIds = isFavorited
        ? Array.from(new Set((this.data.favoriteIds || []).concat([formulaId])))
        : (this.data.favoriteIds || []).filter((id) => Number(id) !== formulaId)

      if (this.data.onlyFavorites && !isFavorited) {
        formulas = formulas.filter((item) => Number(item.id) !== formulaId)
      }
      this.setData({ formulas, favoriteIds })
      wx.showToast({ title: current ? '已取消收藏' : '已收藏', icon: 'none' })
    } catch (err) {
      if (!this._pageAlive) return
      console.error('Toggle formula favorite failed', err)
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
    } finally {
      if (this._favoriteBusyIds) this._favoriteBusyIds.delete(formulaId)
    }
  },

  onReachBottom() {
    this.loadFormulas()
  },

  reload() {
    this.setData({ page: 1, formulas: [], hasMore: true })
    this.loadFormulas(true)
  },

  // ── Navigate ──

  goBack() {
    const pages = getCurrentPages()
    if (pages.length > 1) wx.navigateBack()
    else wx.reLaunch({ url: '/pages/home/home' })
  },

  noop() {},

  goToReader(e) {
    const formulaId = e.currentTarget.dataset.id
    if (formulaId === undefined || formulaId === null || formulaId === '') return

    const sequenceIds = (this.data.formulas || [])
      .map((item) => item.id)
      .filter((id) => id !== undefined && id !== null && id !== '')
    const sequenceIndex = Math.max(0, sequenceIds.findIndex((id) => String(id) === String(formulaId)))

    try {
      wx.setStorageSync(READER_SEQUENCE_KEY, {
        ids: sequenceIds,
        index: sequenceIndex,
        savedAt: formulaNowMs(),
        subjectCode: this.data.activeSubject,
        chapterId: this.data.activeChapterId,
        searchValue: this.data.searchValue,
        libraryType: this.data.activeLibraryType,
        studyCardType: this.data.activeStudyCardType,
      })
    } catch (_) {}

    wx.navigateTo({
      url: `/subpackages/formulas/reader/index?id=${encodeURIComponent(formulaId)}&index=${sequenceIndex}&source=library`,
    })
  },

  goToFavorites() {
    wx.navigateTo({
      url: `/subpackages/formulas/library/index?favorites=1`,
    })
  },

  goToRandom() {
    const { activeSubject, activeChapterId, activeTags, activeLibraryType, activeStudyCardType } = this.data
    const params = {
      subject_code: activeSubject,
      library_type: activeLibraryType || LIBRARY_TYPE_FORMULA,
    }
    if (activeSubject === EXAM408_FORMULA_SUBJECT) params.exam_scope = EXAM408_FORMULA_SUBJECT
    if (activeSubject === EXAM408_FORMULA_SUBJECT && activeStudyCardType) params.study_card_type = activeStudyCardType
    if (activeChapterId) params.chapter_id = activeChapterId
    if (activeTags.length) {
      params.tags = this.data.tags
        .filter(t => activeTags.includes(t.id))
        .map(t => t.code)
        .join(',')
    }
    wx.navigateTo({
      url: `/subpackages/formulas/reader/index?random=1&` + Object.entries(params)
        // Avoid destructured callback params for the same SWC runtime-helper issue.
        .map(entry => `${entry[0]}=${entry[1]}`)
        .join('&'),
    })
  },
})

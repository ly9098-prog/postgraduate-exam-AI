const api = require('../../../utils/api')
const auth = require('../../../utils/auth')
const formulaContent = require('../utils/formula-content')
const Parser = require('../utils/mp-html-parser')
const LatexPlugin = require('../utils/katex/index')
const { resolveGraphImageUrl, resolveGraphThumbnailUrl } = require('../utils/formula-graph')

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
const PRODUCT_EXAM_SCOPE = 'exam408'

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
    subjects: [],
    activeSubject: '',
    activeSubjectName: '408',

    // Content type tabs
    libraryTabs: [
      { key: LIBRARY_TYPE_FORMULA, name: '公式', active: true },
      { key: LIBRARY_TYPE_FUNCTION_GRAPH, name: '函数图像', active: false },
    ],
    activeLibraryType: LIBRARY_TYPE_FORMULA,

    // 408 memory-card semantic type
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
      const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
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
      var params = { exam_scope: PRODUCT_EXAM_SCOPE }
      // Pass library_type so the catalog can show accurate available_count
      if (this.data.activeLibraryType && this.data.activeLibraryType !== LIBRARY_TYPE_FORMULA) {
        params.library_type = this.data.activeLibraryType
      }
      if (this.data.activeStudyCardType) params.study_card_type = this.data.activeStudyCardType
      if (typeof this.data.onlyFavorites !== 'undefined' && this.data.onlyFavorites) {
        params.favorite_only = true
      }
      var url = '/formulas/catalog'
      if (Object.keys(params).length) {
        url += '?' + Object.keys(params).map(function(k) { return k + '=' + encodeURIComponent(params[k]) }).join('&')
      }
      const data = await api.request('GET', url)
      if (!this._pageAlive || requestVersion !== this._catalogRequestVersion) return
      const catalog = this.normalizeCatalog(data?.items || [])
      const currentCode = this.data.activeSubject
      const currentSubject = catalog.find((subject) => subject.code === currentCode)
      const activeCatalogSubject = currentSubject || catalog[0] || null
      const activeSubject = activeCatalogSubject ? activeCatalogSubject.code : ''
      const subjects = catalog.map((subject) => ({
        code: subject.code,
        name: subject.name,
        active: subject.code === activeSubject,
      }))
      const subjectChanged = activeSubject !== currentCode
      this.setData({
        catalog,
        subjects,
        activeSubject,
        activeSubjectName: activeCatalogSubject ? activeCatalogSubject.name : '408',
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
    return (items || []).map((subject, subjectIndex) => {
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
      const data = await api.request('GET', '/formulas/tags')
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
    this.setData({
      subjects,
      activeSubject: code,
      activeSubjectName: selectedSubject?.name || '选择学科',
      activeChapterId: null,
      activeTags: [],
      searchValue: '',
      onlyFavorites: false,
      favoriteIds: [],
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

  // ── 408 Study Card Type ──

  onStudyCardTypeChange(e) {
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
    let activeTags = [...this.data.activeTags]
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
    const requestVersion = this._replaceRequestVersion || 0
    const { loading, loadingMore, initialLoading, page, pageSize, activeSubject, activeChapterId,
            activeTags, searchValue, onlyFavorites, hasMore, activeLibraryType, activeStudyCardType } = this.data
    if (loading || loadingMore || (initialLoading && !replace) || !hasMore) return
    const loadingFlag = replace ? 'initialLoading' : 'loadingMore'
    this.setData({ [loadingFlag]: true, loadError: false })

    try {
      const baseParams = {
        exam_scope: PRODUCT_EXAM_SCOPE,
        subject_code: activeSubject,
        page_size: pageSize,
        library_type: activeLibraryType || LIBRARY_TYPE_FORMULA,
      }
      if (activeStudyCardType) baseParams.study_card_type = activeStudyCardType
      if (activeChapterId) baseParams.chapter_id = activeChapterId
      if (activeTags.length) {
        const tagCodes = this.data.tags
          .filter(t => activeTags.includes(t.id))
          .map(t => t.code)
          .join(',')
        if (tagCodes) baseParams.tags = tagCodes
      }
      if (searchValue) baseParams.q = searchValue
      if (onlyFavorites) baseParams.favorite_only = true

      // Always use /formulas — it supports all filter params including favorite_only
      const url = '/formulas'

      let requestPage = page
      let responseData = null
      let rawItems = []
      let items = []
      let attempts = 0

      // The backend is expected to filter before pagination. The small client
      // still performs the same classification as a compatibility fallback so
      // older deployments do not mix pure formulas into the graph tab. When a
      // legacy page contains no graph, scan a few following pages automatically
      // to avoid showing a false empty state.
      do {
        responseData = await api.request('GET', url, { ...baseParams, page: requestPage })
        rawItems = responseData?.items || []
        const decorated = this.decorateFormulaItems(rawItems)
        items = filterFormulaItemsByLibraryType(decorated, activeLibraryType)
        requestPage += 1
        attempts += 1
      } while (
        activeLibraryType === LIBRARY_TYPE_FUNCTION_GRAPH &&
        items.length === 0 &&
        rawItems.length === pageSize &&
        attempts < MAX_GRAPH_FALLBACK_PAGES
      )

      if (!this._pageAlive || requestVersion !== (this._replaceRequestVersion || 0)) return

      const rawTotal = responseData?.filtered_total ?? responseData?.total
      const parsedTotal = Number(rawTotal)
      const hasKnownTotal = Number.isFinite(parsedTotal) && parsedTotal >= 0
      const mergedFormulas = replace
        ? items
        : [...this.data.formulas, ...items].filter((item, index, list) => (
          list.findIndex((candidate) => String(candidate.id) === String(item.id)) === index
        ))
      const fetchedThroughPage = Math.max(0, requestPage - 1)
      const totalItems = hasKnownTotal ? parsedTotal : mergedFormulas.length
      const hasMoreByResponse = rawItems.length === pageSize
      this.setData({
        formulas: mergedFormulas,
        total: totalItems,
        page: requestPage,
        hasMore: hasKnownTotal
          ? fetchedThroughPage * pageSize < totalItems
          : hasMoreByResponse,
        initialLoading: false,
        loadingMore: false,
      })
    } catch (e) {
      if (!this._pageAlive || requestVersion !== (this._replaceRequestVersion || 0)) return
      console.error('Failed to load formulas', e)
      const shouldReplaceWithError = replace || !(this.data.formulas || []).length
      this.setData({
        initialLoading: false,
        loadingMore: false,
        loadError: shouldReplaceWithError,
        loadErrorMessage: shouldReplaceWithError ? (e.message || '加载失败') : '',
      })
      if (!shouldReplaceWithError) {
        wx.showToast({ title: '加载更多失败，请重试', icon: 'none' })
      }
    }
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
      return {
        ...item,
        titleNodes: renderFormulaTitleNodes(item.title),
        graphImageUrl,
        graphThumbnailUrl,
        graphPreviewUrl: graphImageUrl || graphThumbnailUrl,
        isFunctionGraph,
        studyCardTypeLabel: getStudyCardTypeLabel(item),
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
          exam_scope: PRODUCT_EXAM_SCOPE,
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
      wx.showToast({ title: '请先登录', icon: 'none' })
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
        ? Array.from(new Set([...(this.data.favoriteIds || []), formulaId]))
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
        savedAt: Date.now(),
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
    if (activeStudyCardType) params.study_card_type = activeStudyCardType
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

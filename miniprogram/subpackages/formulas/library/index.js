const api = require('../../../utils/api')
const auth = require('../../../utils/auth')

const READER_SEQUENCE_KEY = 'formula_reader_sequence_v2'
const SEARCH_DEBOUNCE_MS = 500

Page({
  data: {
    // Subject tabs
    subjects: [
      { code: 'math2_high_math', name: '高等数学', active: true },
      { code: 'math2_linear_algebra', name: '线性代数', active: false },
    ],
    activeSubject: 'math2_high_math',

    // Catalog tree
    catalog: [],
    chapters: [],
    activeChapterId: null,

    // Tags
    tags: [],
    activeTags: [],

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
    showChapterPicker: false,
    showTagPicker: false,

    // Loading states
    initialLoading: true,
    loadingMore: false,
    loadError: false,
    loadErrorMessage: '',
  },

  onLoad(options = {}) {
    const onlyFavorites = options.favorites === '1'
    if (onlyFavorites) this.setData({ onlyFavorites: true })
    this.loadCatalog()
    this.loadTags()
    this.loadFavoriteIds()
    this.loadFormulas(true)
  },

  onPullDownRefresh() {
    this.setData({ page: 1, formulas: [], hasMore: true })
    this.loadFormulas(true)
      .then(() => wx.stopPullDownRefresh())
      .catch(() => wx.stopPullDownRefresh())
  },

  // ── Catalog ──

  async loadCatalog() {
    try {
      const data = await api.request('GET', '/formulas/catalog')
      const catalog = this.normalizeCatalog(data?.items || [])
      this.setData({ catalog })
      this.updateChapters()
    } catch (e) {
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
    try {
      const data = await api.request('GET', '/formulas/tags')
      this.setData({ tags: data?.items || [] })
    } catch (e) {
      console.error('Failed to load formula tags', e)
    }
  },

  updateChapters() {
    // Find the currently active subject in catalog
    const { catalog, activeSubject } = this.data
    const subject = catalog.find(s => s.code === activeSubject)
    if (subject) {
      this.setData({
        chapters: (subject.children || []).map((chapter) => ({ ...chapter, active: false })),
        activeChapterId: null,
      })
    } else {
      this.setData({ chapters: [], activeChapterId: null })
    }
  },

  // ── Subject Switch ──

  onSubjectChange(e) {
    const code = e.currentTarget.dataset.code
    if (code === this.data.activeSubject) return
    const subjects = this.data.subjects.map(s => ({
      ...s, active: s.code === code,
    }))
    this.setData({
      subjects,
      activeSubject: code,
      activeChapterId: null,
      activeTags: [],
      searchValue: '',
      onlyFavorites: false,
      favoriteIds: [],
      page: 1,
      formulas: [],
      hasMore: true,
    })
    this.updateChapters()
    this.loadFormulas(true)
  },

  // ── Chapter Filter ──

  toggleChapterPicker() {
    this.setData({ showChapterPicker: !this.data.showChapterPicker })
  },

  onChapterSelect(e) {
    const rawId = e.currentTarget.dataset.id
    const chapterId = rawId === 0 || rawId === '0' || rawId === '' ? null : rawId
    const isCurrent = chapterId != null && String(chapterId) === String(this.data.activeChapterId)
    const nextChapterId = isCurrent ? null : chapterId
    const chapters = (this.data.chapters || []).map((chapter) => ({
      ...chapter,
      active: nextChapterId != null && String(chapter.id) === String(nextChapterId),
    }))

    this.setData({
      chapters,
      activeChapterId: nextChapterId,
      showChapterPicker: false,
      page: 1,
      formulas: [],
      hasMore: true,
    })
    this.loadFormulas(true)
  },

  // ── Tag Filter ──

  toggleTagPicker() {
    this.setData({
      showTagPicker: !this.data.showTagPicker,
      showChapterPicker: false,
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

  onUnload() {
    if (this._searchTimer) clearTimeout(this._searchTimer)
    this._searchTimer = null
  },

  // ── Favorites toggle ──

  toggleFavoritesOnly() {
    this.setData({
      onlyFavorites: !this.data.onlyFavorites,
      page: 1,
      formulas: [],
      hasMore: true,
    })
    this.loadFormulas(true)
  },

  // ── Load Formulas ──

  async loadFormulas(replace = false) {
    if (replace) this._replaceRequestVersion = (this._replaceRequestVersion || 0) + 1
    const requestVersion = this._replaceRequestVersion || 0
    const { loading, loadingMore, initialLoading, page, pageSize, activeSubject, activeChapterId,
            activeTags, searchValue, onlyFavorites, hasMore } = this.data
    if (loading || loadingMore || (initialLoading && !replace) || !hasMore) return
    const loadingFlag = replace ? 'initialLoading' : 'loadingMore'
    this.setData({ [loadingFlag]: true, loadError: false })

    try {
      const params = {
        subject_code: activeSubject,
        page,
        page_size: pageSize,
      }
      if (activeChapterId) params.chapter_id = activeChapterId
      if (activeTags.length) {
        const tagCodes = this.data.tags
          .filter(t => activeTags.includes(t.id))
          .map(t => t.code)
          .join(',')
        if (tagCodes) params.tags = tagCodes
      }
      if (searchValue) params.q = searchValue
      if (onlyFavorites) params.favorite_only = true

      const url = onlyFavorites
        ? '/formulas/favorites/list'
        : '/formulas'

      const data = await api.request('GET', url, params)
      const items = this.decorateFormulaItems(data?.items || [])
      if (requestVersion !== (this._replaceRequestVersion || 0)) return

      this.setData({
        formulas: replace ? items : [...this.data.formulas, ...items],
        total: data?.total || 0,
        page: page + 1,
        hasMore: items.length === pageSize,
        initialLoading: false,
        loadingMore: false,
      })
    } catch (e) {
      if (requestVersion !== (this._replaceRequestVersion || 0)) return
      console.error('Failed to load formulas', e)
      this.setData({
        initialLoading: false,
        loadingMore: false,
        loadError: true,
        loadErrorMessage: e.message || '加载失败',
      })
    }
  },

  decorateFormulaItems(items) {
    const favoriteIds = this.data.favoriteIds || []
    return (items || []).map((item) => ({
      ...item,
      isFavorited: Boolean(item.isFavorited || item.is_favorited || favoriteIds.includes(Number(item.id))),
    }))
  },

  async loadFavoriteIds() {
    if (!auth.isLoggedIn()) return
    try {
      const data = await api.request('GET', '/formulas/favorites/list', { page: 1, page_size: 200 })
      const favoriteIds = (data?.items || []).map((item) => Number(item.id)).filter(Boolean)
      const formulas = (this.data.formulas || []).map((item) => ({
        ...item,
        isFavorited: Boolean(item.isFavorited || item.is_favorited || favoriteIds.includes(Number(item.id))),
      }))
      this.setData({ favoriteIds, formulas })
    } catch (e) {
      console.warn('Failed to load formula favorites', e)
    }
  },

  async toggleFormulaFavorite(e) {
    if (!auth.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }

    const formulaId = Number(e.currentTarget.dataset.id)
    if (!formulaId) return
    const formulas = (this.data.formulas || []).map((item) => ({ ...item }))
    const index = formulas.findIndex((item) => Number(item.id) === formulaId)
    if (index < 0) return

    const current = Boolean(formulas[index].isFavorited || formulas[index].is_favorited)
    try {
      if (current) {
        await api.request('DELETE', `/formulas/${formulaId}/favorite`)
      } else {
        await api.request('PUT', `/formulas/${formulaId}/favorite`)
      }

      formulas[index].isFavorited = !current
      formulas[index].is_favorited = !current
      const favoriteIds = current
        ? (this.data.favoriteIds || []).filter((id) => Number(id) !== formulaId)
        : Array.from(new Set([...(this.data.favoriteIds || []), formulaId]))

      if (this.data.onlyFavorites && current) formulas.splice(index, 1)
      this.setData({ formulas, favoriteIds })
      wx.showToast({ title: current ? '已取消收藏' : '已收藏', icon: 'none' })
    } catch (err) {
      console.error('Toggle formula favorite failed', err)
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
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
    const { activeSubject, activeChapterId, activeTags } = this.data
    const params = { subject_code: activeSubject }
    if (activeChapterId) params.chapter_id = activeChapterId
    if (activeTags.length) {
      params.tags = this.data.tags
        .filter(t => activeTags.includes(t.id))
        .map(t => t.code)
        .join(',')
    }
    wx.navigateTo({
      url: `/subpackages/formulas/reader/index?random=1&` + Object.entries(params)
        .map(([k, v]) => `${k}=${v}`)
        .join('&'),
    })
  },
})

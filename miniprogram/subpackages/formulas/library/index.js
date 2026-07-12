const api = require('../../../utils/api')

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
    searchTimer: null,

    // Favorites
    onlyFavorites: false,

    // List
    formulas: [],
    page: 1,
    pageSize: 20,
    total: 0,
    loading: false,
    hasMore: true,

    // UI state
    showChapterPicker: false,
    showTagPicker: false,
  },

  onLoad() {
    this.loadCatalog()
    this.loadTags()
    this.loadFormulas(true)
  },

  onPullDownRefresh() {
    this.setData({ page: 1, formulas: [], hasMore: true })
    this.loadFormulas(true).then(() => wx.stopPullDownRefresh())
  },

  // ── Catalog ──

  async loadCatalog() {
    try {
      const res = await api.request('GET', '/formulas/catalog')
      const catalog = res.data?.items || []
      this.setData({ catalog })
      this.updateChapters()
    } catch (e) {
      console.error('Failed to load formula catalog', e)
    }
  },

  async loadTags() {
    try {
      const res = await api.request('GET', '/formulas/tags')
      this.setData({ tags: res.data?.items || [] })
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
        chapters: subject.children || [],
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
    const chapterId = e.currentTarget.dataset.id
    this.setData({
      activeChapterId: chapterId === this.data.activeChapterId ? null : chapterId,
      showChapterPicker: false,
      page: 1,
      formulas: [],
      hasMore: true,
    })
    this.loadFormulas(true)
  },

  // ── Tag Filter ──

  toggleTagPicker() {
    this.setData({ showTagPicker: !this.data.showTagPicker })
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
    const value = e.detail.value
    if (this.data.searchTimer) clearTimeout(this.data.searchTimer)
    const timer = setTimeout(() => {
      this.setData({
        searchValue: value,
        page: 1,
        formulas: [],
        hasMore: true,
      })
      this.loadFormulas(true)
    }, 300)
    this.setData({ searchTimer: timer })
  },

  onSearchClear() {
    this.setData({ searchValue: '', page: 1, formulas: [], hasMore: true })
    this.loadFormulas(true)
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
    const { loading, page, pageSize, activeSubject, activeChapterId,
            activeTags, searchValue, onlyFavorites, hasMore } = this.data
    if (loading || !hasMore) return
    this.setData({ loading: true })

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

      const res = await api.request('GET', url, params)
      const data = res.data || {}
      const items = data.items || []

      this.setData({
        formulas: replace ? items : [...this.data.formulas, ...items],
        total: data.total || 0,
        page: page + 1,
        hasMore: items.length === pageSize,
        loading: false,
      })
    } catch (e) {
      console.error('Failed to load formulas', e)
      this.setData({ loading: false })
    }
  },

  onReachBottom() {
    this.loadFormulas()
  },

  // ── Navigate ──

  goToReader(e) {
    const formulaId = e.currentTarget.dataset.id
    if (!formulaId) return
    wx.navigateTo({
      url: `/subpackages/formulas/reader/index?id=${formulaId}`,
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

const api = require('../../../utils/api')
const auth = require('../../../utils/auth')

// Maximum cards kept in the window: current ± 1
const WINDOW_SIZE = 3

Page({
  data: {
    displayCards: [],
    currentIndex: 0,
    loading: true,

    // Random mode
    isRandom: false,
    randomParams: {},
  },

  onLoad(options) {
    const formulaId = options.id ? parseInt(options.id) : null
    const isRandom = options.random === '1'

    if (isRandom) {
      const params = {}
      if (options.subject_code) params.subject_code = options.subject_code
      if (options.chapter_id) params.chapter_id = options.chapter_id
      if (options.tags) params.tags = options.tags
      this.data.isRandom = true
      this.data.randomParams = params
      this.loadRandomCard()
    } else if (formulaId) {
      this.loadCard(formulaId)
    }
  },

  // ── Load single card ──

  async loadCard(formulaId) {
    this.setData({ loading: true })
    try {
      const res = await api.request('GET', `/formulas/${formulaId}`)
      const card = this.enrichCard(res.data || {})
      this.setData({
        displayCards: [card],
        currentIndex: 0,
        loading: false,
      })
    } catch (e) {
      console.error('Failed to load formula', e)
      wx.showToast({ title: '加载失败', icon: 'none' })
      this.setData({ loading: false })
    }
  },

  // ── Random mode ──

  async loadRandomCard() {
    this.setData({ loading: true })
    try {
      const params = { ...this.data.randomParams }
      const res = await api.request('GET', '/formulas/random/next', params)
      const card = this.enrichCard(res.data || {})
      // Track exclude ids for future random calls
      this.data._excludeIds = this.data._excludeIds || []
      if (card.id) this.data._excludeIds.push(card.id)

      this.setData({
        displayCards: [card],
        currentIndex: 0,
        loading: false,
      })
    } catch (e) {
      console.error('Failed to load random formula', e)
      wx.showToast({ title: '没有更多公式', icon: 'none' })
      this.setData({ loading: false })
    }
  },

  // ── Enrich card with favorite status and graph URL ──

  async enrichCard(card) {
    if (!card) return card
    // Check favorite status
    if (auth.isLoggedIn()) {
      try {
        const res = await api.request('GET', '/formulas/favorites/list', { page: 1, page_size: 100 })
        const favIds = (res.data?.items || []).map(f => f.id)
        card.isFavorited = favIds.includes(card.id)
      } catch (e) {
        card.isFavorited = false
      }
    } else {
      card.isFavorited = false
    }
    return card
  },

  // ── Swiper change ──

  async onSwiperChange(e) {
    const idx = e.detail.current
    if (idx === this.data.currentIndex) return

    this.setData({ currentIndex: idx })

    // In random mode, load new random card when reaching the end
    if (this.data.isRandom && idx >= this.data.displayCards.length - 1) {
      await this.loadRandomCard()
    }
  },

  // ── Navigation ──

  goPrev() {
    const idx = this.data.currentIndex
    if (idx > 0) {
      this.setData({ currentIndex: idx - 1 })
    }
  },

  goNext() {
    const idx = this.data.currentIndex
    if (idx < this.data.displayCards.length - 1) {
      this.setData({ currentIndex: idx + 1 })
    }
  },

  // ── Favorite Toggle ──

  async toggleFavorite(e) {
    if (!auth.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }
    const cardId = parseInt(e.currentTarget.dataset.id)
    const cards = [...this.data.displayCards]
    const cardIdx = cards.findIndex(c => c.id === cardId)
    if (cardIdx < 0) return

    const card = { ...cards[cardIdx] }
    try {
      if (card.isFavorited) {
        await api.request('DELETE', `/formulas/${cardId}/favorite`)
        card.isFavorited = false
        wx.showToast({ title: '已取消收藏', icon: 'none' })
      } else {
        await api.request('PUT', `/formulas/${cardId}/favorite`)
        card.isFavorited = true
        wx.showToast({ title: '已收藏', icon: 'success' })
      }
      cards[cardIdx] = card
      this.setData({ displayCards: cards })
    } catch (e) {
      console.error('Toggle favorite failed', e)
      wx.showToast({ title: '操作失败', icon: 'none' })
    }
  },
})

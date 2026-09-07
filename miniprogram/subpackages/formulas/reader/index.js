const api = require('../../../utils/api')
const auth = require('../../../utils/auth')
const { resolveGraphImageUrl, resolveGraphThumbnailUrl } = require('../utils/formula-graph')

const MAX_RANDOM_HISTORY = 24
const READER_SEQUENCE_KEY = 'formula_reader_sequence_v2'
const SEQUENCE_TTL = 30 * 60 * 1000
const TRANSITION_OUT_MS = 150
const TRANSITION_IN_DELAY_MS = 36
const PRODUCT_EXAM_SCOPE = 'exam408'

function normalizeId(value) {
  if (value === undefined || value === null || value === '') return null
  const text = String(value)
  return /^\d+$/.test(text) ? Number(text) : text
}

function sameId(a, b) {
  return a !== null && b !== null && String(a) === String(b)
}

function normalizeSequence(values) {
  const result = []
  ;(values || []).forEach((value) => {
    const id = normalizeId(value)
    if (id !== null && !result.some((item) => sameId(item, id))) result.push(id)
  })
  return result
}

Page({
  data: {
    displayCards: [],
    currentCard: null,
    currentIndex: 0,
    loading: true,
    loadingNext: false,
    favoriteBusy: false,
    loadError: false,
    errorText: '',
    formulaId: null,
    sequenceIds: [],
    sequenceIndex: 0,
    canGoPrev: false,
    canGoNext: false,
    readerScrollTop: 0,
    transitionClass: '',

    isRandom: false,
    randomParams: {},
  },

  onLoad(options = {}) {
    const formulaId = normalizeId(options.id)
    const isRandom = options.random === '1'
    let sequenceIds = normalizeSequence(String(options.ids || '').split(',').filter(Boolean))

    if (!isRandom && sequenceIds.length <= 1) {
      try {
        const cached = wx.getStorageSync(READER_SEQUENCE_KEY) || {}
        const cachedIds = normalizeSequence(cached.ids)
        const fresh = Date.now() - Number(cached.savedAt || 0) < SEQUENCE_TTL
        if (fresh && cachedIds.some((id) => sameId(id, formulaId))) sequenceIds = cachedIds
      } catch (_) {}
    }

    const requestedIndex = parseInt(options.index, 10)
    const inferredIndex = sequenceIds.findIndex((id) => sameId(id, formulaId))
    const sequenceIndex = Number.isFinite(requestedIndex) && requestedIndex >= 0
      ? Math.min(requestedIndex, Math.max(0, sequenceIds.length - 1))
      : Math.max(0, inferredIndex)

    this.setData({ formulaId, isRandom, sequenceIds, sequenceIndex }, () => this.syncNavigationState())

    if (isRandom) {
      const params = { exam_scope: PRODUCT_EXAM_SCOPE }
      if (options.subject_code) params.subject_code = options.subject_code
      if (options.chapter_id) params.chapter_id = options.chapter_id
      if (options.tags) params.tags = options.tags
      if (options.library_type) params.library_type = options.library_type
      this.setData({ randomParams: params })
      this.loadRandomCard({ append: false })
      return
    }

    if (formulaId !== null) {
      this.loadCard(formulaId)
      return
    }

    this.setData({
      loading: false,
      loadError: true,
      errorText: '缺少公式编号，请返回公式库重新选择',
    })
  },

  onUnload() {
    clearTimeout(this._transitionTimer)
    clearTimeout(this._transitionInTimer)
    clearTimeout(this._formulaGestureTimer)
    this._cardRequestToken = (this._cardRequestToken || 0) + 1
    this._randomRequestToken = (this._randomRequestToken || 0) + 1
    this._readerGesture = null
    this._formulaGestureActive = false
  },

  goBack() {
    const pages = getCurrentPages()
    if (pages.length > 1) wx.navigateBack()
    else wx.reLaunch({ url: '/subpackages/formulas/library/index' })
  },

  syncNavigationState() {
    const { isRandom, currentIndex, sequenceIndex } = this.data
    const displayCards = Array.isArray(this.data.displayCards) ? this.data.displayCards : []
    const sequenceIds = Array.isArray(this.data.sequenceIds) ? this.data.sequenceIds : []
    this.setData({
      canGoPrev: isRandom ? currentIndex > 0 : sequenceIndex > 0 && sequenceIds.length > 0,
      canGoNext: isRandom ? true : sequenceIds.length > 1 && sequenceIndex >= 0 && sequenceIndex < sequenceIds.length - 1,
    })
  },

  async fetchCard(formulaId) {
    const data = await api.request('GET', `/formulas/${formulaId}`, { exam_scope: PRODUCT_EXAM_SCOPE })
    return this.enrichCard(data || {})
  },

  applyCardTransition(card, direction, patch = {}) {
    if (!card || typeof card !== 'object') {
      this.setData({ loadingNext: false, transitionClass: '' })
      return
    }
    clearTimeout(this._transitionTimer)
    clearTimeout(this._transitionInTimer)
    clearTimeout(this._formulaGestureTimer)
    this._readerGesture = null
    this._formulaGestureActive = false

    const goingNext = direction !== 'prev'
    const outClass = goingNext ? 'fr-slide-out-left' : 'fr-slide-out-right'
    const inClass = goingNext ? 'fr-slide-in-right' : 'fr-slide-in-left'

    this.setData({ transitionClass: outClass })
    this._transitionTimer = setTimeout(() => {
      this.setData({
        ...patch,
        currentCard: card,
        loading: false,
        loadingNext: false,
        transitionClass: inClass,
      }, () => {
        this.resetReaderScroll()
        this.syncNavigationState()
        this._transitionInTimer = setTimeout(() => {
          this.setData({ transitionClass: '' })
        }, TRANSITION_IN_DELAY_MS)
      })
    }, TRANSITION_OUT_MS)
  },

  async loadCard(formulaId, {
    transition = false,
    sequenceIndex = this.data.sequenceIndex,
    direction = 'next',
  } = {}) {
    const requestToken = (this._cardRequestToken || 0) + 1
    this._cardRequestToken = requestToken
    const loadingKey = transition ? 'loadingNext' : 'loading'
    this.setData({ [loadingKey]: true, loadError: false, errorText: '' })

    try {
      const card = await this.fetchCard(formulaId)
      if (requestToken !== this._cardRequestToken) return
      if (!card || typeof card !== 'object') throw new Error('公式数据无效')
      const resolvedId = normalizeId(card.id || formulaId)
      const patch = {
        displayCards: [card],
        currentIndex: 0,
        formulaId: resolvedId,
        sequenceIndex,
      }

      if (transition && this.data.currentCard) {
        this.applyCardTransition(card, direction, patch)
      } else {
        this.setData({
          ...patch,
          currentCard: card,
          loading: false,
          loadingNext: false,
          transitionClass: '',
        }, () => {
          this.resetReaderScroll()
          this.syncNavigationState()
        })
      }

      if (!this.data.isRandom && this.data.sequenceIds.length <= 1) {
        this.ensureSequence(card).catch(() => {})
      }
    } catch (err) {
      if (requestToken !== this._cardRequestToken) return
      console.error('Failed to load formula', err)
      if (transition) {
        this.setData({ loadingNext: false, transitionClass: '' })
        wx.showToast({ title: '切换失败，请重试', icon: 'none' })
      } else {
        this.setData({
          loading: false,
          loadError: true,
          errorText: err && err.message ? err.message : '公式加载失败，请稍后重试',
        })
      }
    }
  },

  async ensureSequence(card) {
    const previousId = normalizeId(card.prev_id || card.previous_id || (card.navigation && card.navigation.prev_id))
    const nextId = normalizeId(card.next_id || card.following_id || (card.navigation && card.navigation.next_id))
    const currentId = normalizeId(card.id || this.data.formulaId)

    if (previousId !== null || nextId !== null) {
      const ids = normalizeSequence([previousId, currentId, nextId])
      const index = Math.max(0, ids.findIndex((id) => sameId(id, currentId)))
      this.setData({ sequenceIds: ids, sequenceIndex: index }, () => this.syncNavigationState())
      return
    }

    const params = { page: 1, page_size: 100, exam_scope: PRODUCT_EXAM_SCOPE }
    const subjectCode = card.subject_code || card.subjectCode || (card.subject && card.subject.code)
    const chapterId = card.chapter_id || card.chapterId || (card.chapter && card.chapter.id)
    if (subjectCode) params.subject_code = subjectCode
    if (chapterId) params.chapter_id = chapterId
    if (!subjectCode && !chapterId) return

    const data = await api.request('GET', '/formulas', params)
    const ids = normalizeSequence((data && data.items ? data.items : []).map((item) => item.id))
    const index = ids.findIndex((id) => sameId(id, currentId))
    if (ids.length > 1 && index >= 0) {
      this.setData({ sequenceIds: ids, sequenceIndex: index }, () => this.syncNavigationState())
    }
  },

  async loadRandomCard({ append = false } = {}) {
    const requestToken = (this._randomRequestToken || 0) + 1
    this._randomRequestToken = requestToken
    const loadingKey = append ? 'loadingNext' : 'loading'
    this.setData({ [loadingKey]: true, loadError: false, errorText: '' })

    try {
      const params = { exam_scope: PRODUCT_EXAM_SCOPE, ...this.data.randomParams }
      if (this._excludeIds && this._excludeIds.length > 0) {
        params.exclude_ids = this._excludeIds.slice(-50).join(',')
      }

      const data = await api.request('GET', '/formulas/random/next', params)
      if (requestToken !== this._randomRequestToken) return
      const card = await this.enrichCard(data || {})
      if (requestToken !== this._randomRequestToken) return
      if (!card || !card.id) throw new Error('没有更多可背诵的公式')

      this._excludeIds = this._excludeIds || []
      this._excludeIds.push(normalizeId(card.id))

      let cards = append ? [...this.data.displayCards, card] : [card]
      if (cards.length > MAX_RANDOM_HISTORY) cards = cards.slice(-MAX_RANDOM_HISTORY)
      const currentIndex = append ? cards.length - 1 : 0
      const patch = { displayCards: cards, currentIndex }

      if (append && this.data.currentCard) {
        this.applyCardTransition(cards[currentIndex], 'next', patch)
      } else {
        this.setData({
          ...patch,
          currentCard: cards[currentIndex],
          loading: false,
          loadingNext: false,
          transitionClass: '',
        }, () => {
          this.resetReaderScroll()
          this.syncNavigationState()
        })
      }
    } catch (err) {
      if (requestToken !== this._randomRequestToken) return
      console.error('Failed to load random formula', err)
      if (append) {
        this.setData({ loadingNext: false, transitionClass: '' })
        wx.showToast({ title: '没有更多公式', icon: 'none' })
      } else {
        this.setData({
          loading: false,
          loadError: true,
          errorText: err && err.message ? err.message : '暂时没有可背诵的公式',
        })
      }
    }
  },

  async _getFavoriteIds() {
    if (!auth.isLoggedIn()) return []
    if (Array.isArray(this._favoriteIds)) return this._favoriteIds

    try {
      const data = await api.request('GET', '/formulas/favorites/list', { page: 1, page_size: 200, exam_scope: PRODUCT_EXAM_SCOPE })
      this._favoriteIds = (data && data.items ? data.items : [])
        .map((item) => normalizeId(item.id))
        .filter((id) => id !== null)
    } catch (_) {
      this._favoriteIds = []
    }
    return this._favoriteIds
  },

  async enrichCard(card) {
    if (!card) return card
    const favoriteIds = await this._getFavoriteIds()
    return {
      ...card,
      graphImageUrl: resolveGraphImageUrl(card),
      graphThumbnailUrl: resolveGraphThumbnailUrl(card),
      isFavorited: Boolean(card.isFavorited || card.is_favorited || favoriteIds.some((id) => sameId(id, normalizeId(card.id)))),
    }
  },

  resetReaderScroll() {
    this.setData({ readerScrollTop: 1 }, () => this.setData({ readerScrollTop: 0 }))
  },

  onFormulaGestureStart() {
    clearTimeout(this._formulaGestureTimer)
    this._formulaGestureActive = true
    this._readerGesture = null
  },

  onFormulaGestureEnd() {
    clearTimeout(this._formulaGestureTimer)
    this._formulaGestureTimer = setTimeout(() => {
      this._formulaGestureActive = false
    }, 70)
  },

  onReaderTouchStart(e = {}) {
    if (this.data.loadingNext || this._formulaGestureActive) return
    const touch = e.touches && e.touches[0]
    if (!touch) return
    this._readerGesture = { startX: touch.clientX, startY: touch.clientY, dx: 0, dy: 0, axis: '' }
  },

  onReaderTouchMove(e = {}) {
    if (this._formulaGestureActive) {
      this._readerGesture = null
      return
    }
    const gesture = this._readerGesture
    const touch = e.touches && e.touches[0]
    if (!gesture || !touch) return
    gesture.dx = touch.clientX - gesture.startX
    gesture.dy = touch.clientY - gesture.startY
    if (!gesture.axis && (Math.abs(gesture.dx) > 8 || Math.abs(gesture.dy) > 8)) {
      gesture.axis = Math.abs(gesture.dx) > Math.abs(gesture.dy) * 1.12 ? 'x' : 'y'
    }
  },

  onReaderTouchEnd(e = {}) {
    const gesture = this._readerGesture
    this._readerGesture = null
    if (this._formulaGestureActive || !gesture || gesture.axis !== 'x' || this.data.loadingNext) return

    const touch = e.changedTouches && e.changedTouches[0]
    if (touch) {
      gesture.dx = touch.clientX - gesture.startX
      gesture.dy = touch.clientY - gesture.startY
    }
    const horizontalDistance = Math.abs(gesture.dx)
    const verticalDistance = Math.abs(gesture.dy)
    if (horizontalDistance < 40 || verticalDistance > horizontalDistance * 0.8) return

    if (gesture.dx < 0) this.goNext()
    else this.goPrev()
  },

  onReaderTouchCancel() {
    this._readerGesture = null
  },

  switchRandomCard(nextIndex, direction) {
    const cards = Array.isArray(this.data.displayCards) ? this.data.displayCards : []
    const card = cards[nextIndex]
    if (!card) return
    this.setData({ loadingNext: true })
    this.applyCardTransition(card, direction, { currentIndex: nextIndex })
  },

  goPrev() {
    if (this.data.loadingNext || !this.data.canGoPrev) return
    if (this.data.isRandom) {
      this.switchRandomCard(this.data.currentIndex - 1, 'prev')
      return
    }

    const ids = Array.isArray(this.data.sequenceIds) ? this.data.sequenceIds : []
    const sequenceIndex = this.data.sequenceIndex - 1
    const formulaId = ids[sequenceIndex]
    if (formulaId !== null && formulaId !== undefined) {
      this.loadCard(formulaId, { transition: true, sequenceIndex, direction: 'prev' })
    }
  },

  goNext() {
    if (this.data.loadingNext || !this.data.canGoNext) return
    if (!this.data.isRandom) {
      const ids = Array.isArray(this.data.sequenceIds) ? this.data.sequenceIds : []
      const sequenceIndex = this.data.sequenceIndex + 1
      const formulaId = ids[sequenceIndex]
      if (formulaId !== null && formulaId !== undefined) {
        this.loadCard(formulaId, { transition: true, sequenceIndex, direction: 'next' })
      }
      return
    }

    const cards = Array.isArray(this.data.displayCards) ? this.data.displayCards : []
    const nextIndex = this.data.currentIndex + 1
    if (nextIndex < cards.length) {
      this.switchRandomCard(nextIndex, 'next')
      return
    }
    this.loadRandomCard({ append: true })
  },

  async toggleFavorite(e) {
    if (!auth.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }

    const cardId = normalizeId(e.currentTarget.dataset.id)
    if (cardId === null || this.data.favoriteBusy) return

    const cards = this.data.displayCards.map((item) => ({ ...item }))
    const cardIndex = cards.findIndex((item) => sameId(normalizeId(item.id), cardId))
    if (cardIndex < 0) return

    const card = cards[cardIndex]
    const wasFavorited = Boolean(card.isFavorited)
    this.setData({ favoriteBusy: true })

    try {
      if (wasFavorited) await api.request('DELETE', `/formulas/${cardId}/favorite`)
      else await api.request('PUT', `/formulas/${cardId}/favorite`)

      card.isFavorited = !wasFavorited
      cards[cardIndex] = card
      this._favoriteIds = this._favoriteIds || []
      this._favoriteIds = wasFavorited
        ? this._favoriteIds.filter((id) => !sameId(id, cardId))
        : [...this._favoriteIds.filter((id) => !sameId(id, cardId)), cardId]

      this.setData({
        displayCards: cards,
        currentCard: cards[this.data.currentIndex] || card,
        favoriteBusy: false,
      })
      wx.showToast({ title: wasFavorited ? '已取消收藏' : '已收藏', icon: 'none' })
    } catch (err) {
      console.error('Toggle favorite failed', err)
      this.setData({ favoriteBusy: false })
      wx.showToast({ title: '操作失败，请重试', icon: 'none' })
    }
  },

  retryLoad() {
    if (this.data.isRandom) this.loadRandomCard({ append: false })
    else if (this.data.formulaId !== null) this.loadCard(this.data.formulaId)
  },
})

const storage = require('../../../utils/storage')

const DISMISSED_KEY = 'preferences.home.loginHintDismissed'
const LOGIN_GUIDE_VISIBLE_MS = 6000
const LOGIN_ENTRY_ATTENTION_MS = 10000
let shownThisLaunch = false

function overlaps(first, second) {
  return first.left < second.left + second.width && first.left + first.width > second.left &&
    first.top < second.top + second.height && first.top + first.height > second.top
}

function loginGuideLayout(viewport, anchor, guide, menu) {
  if (!viewport || !anchor || !guide) return null
  const values = [viewport.windowWidth, viewport.windowHeight, anchor.left, anchor.top,
    anchor.width, anchor.height, guide.width, guide.height]
  if (!values.every(Number.isFinite)) return null
  const width = guide.width
  if (width <= 32 || guide.height <= 0 || anchor.width <= 0 || anchor.height <= 0) return null
  if (width > Math.min(232, viewport.windowWidth - 32) + .5 || anchor.top < 0) return null
  const center = anchor.left + anchor.width / 2
  const left = Math.max(16, Math.min(center - width / 2, viewport.windowWidth - width - 16))
  const top = anchor.top + anchor.height + 8
  const arrowLeft = center - left
  if (arrowLeft < 12 || arrowLeft > width - 12 || top + guide.height > viewport.windowHeight - 16) return null
  if (menu && menu.width > 0 && menu.height > 0 &&
    (overlaps(anchor, menu) || overlaps({ left, top, width, height: guide.height }, menu) ||
      overlaps({ left: center - 6, top: top - 6, width: 12, height: 12 }, menu))) return null
  return {
    loginGuideLeft: left - anchor.left,
    loginGuideArrowLeft: arrowLeft,
  }
}

const guestLoginGuideMethods = {
  _syncLoginGuide() {
    if (!this._alive || !this._visible || this._authed || !this.data.guestMode) {
      this._dismissLoginGuide()
      return
    }
    if (shownThisLaunch || storage.get(DISMISSED_KEY) === true) return
    shownThisLaunch = true
    this.setData({ showLoginGuide: true, loginGuideReady: false }, () => {
      this._positionLoginGuide()
    })
  },

  _positionLoginGuide() {
    if (!this._alive || !this._visible || !this.data.showLoginGuide) return
    if (typeof wx.createSelectorQuery !== 'function') return this._dismissLoginGuide()
    const sequence = this._loginGuideLayoutSeq = (this._loginGuideLayoutSeq || 0) + 1
    const query = wx.createSelectorQuery().in(this)
    query.select('#home-profile-chip').boundingClientRect()
    query.select('#home-login-guide').boundingClientRect()
    query.exec(rects => {
      if (!this._alive || !this._visible || this._authed || !this.data.showLoginGuide) return
      if (sequence !== this._loginGuideLayoutSeq) return
      let placement = null
      try {
        const menu = typeof wx.getMenuButtonBoundingClientRect === 'function' ? wx.getMenuButtonBoundingClientRect() : null
        placement = loginGuideLayout(wx.getWindowInfo(), rects && rects[0], rects && rects[1], menu)
      } catch (_) {}
      if (!placement) return this._dismissLoginGuide()
      this.setData({ ...placement, loginGuideReady: true }, () => {
        if (!this._alive || !this._visible || this._authed || !this.data.showLoginGuide) return
        if (sequence !== this._loginGuideLayoutSeq || this._loginGuideTimer != null) return
        this._startLoginEntryAttention()
        this._loginGuideTimer = setTimeout(() => {
          this._loginGuideTimer = null
          if (this._alive && this._visible && !this._authed && this.data.showLoginGuide) this._dismissLoginGuide({ preserveEntry: true })
        }, LOGIN_GUIDE_VISIBLE_MS)
      })
      this._listenLoginGuideKeys()
    })
  },

  _listenLoginGuideKeys() {
    if (this._loginGuideKeyListener || typeof wx.onKeyDown !== 'function' || typeof wx.offKeyDown !== 'function') return
    this._loginGuideKeyListener = event => {
      if (event.key === 'Escape' && this._alive && this._visible && this.data.showLoginGuide) {
        this.closeLoginGuide()
      }
    }
    wx.onKeyDown(this._loginGuideKeyListener)
  },

  _startLoginEntryAttention() {
    if (this._loginEntryTimer != null) return
    this.setData({ loginEntryAttention: true })
    this._loginEntryTimer = setTimeout(() => {
      this._loginEntryTimer = null
      if (this._alive && this._visible) this.setData({ loginEntryAttention: false })
    }, LOGIN_ENTRY_ATTENTION_MS)
  },

  _dismissLoginGuide({ preserveEntry = false } = {}) {
    this._pauseLoginGuide({ preserveEntry })
    if (this.data.showLoginGuide || this.data.loginEntryAttention) {
      this.setData({ showLoginGuide: false, loginGuideReady: false,
        loginEntryAttention: preserveEntry && this.data.loginEntryAttention })
    }
  },

  _pauseLoginGuide({ preserveTimer = false, preserveEntry = preserveTimer } = {}) {
    this._loginGuideLayoutSeq = (this._loginGuideLayoutSeq || 0) + 1
    if (!preserveTimer) {
      clearTimeout(this._loginGuideTimer)
      this._loginGuideTimer = null
    }
    if (!preserveEntry) {
      clearTimeout(this._loginEntryTimer)
      this._loginEntryTimer = null
    }
    if (this._loginGuideKeyListener) wx.offKeyDown(this._loginGuideKeyListener)
    this._loginGuideKeyListener = null
  },

  closeLoginGuide() {
    storage.set(DISMISSED_KEY, true)
    this._dismissLoginGuide()
  },

  openLoginGuide() {
    if (!this._alive || !this._visible || !this.data.showLoginGuide || !this.data.loginGuideReady || this._authed) return
    this._dismissLoginGuide()
    return this.openProfileSheet()
  },

  dismissLoginGuideFromPage() {
    if (this.data.showLoginGuide || this.data.loginEntryAttention) this._dismissLoginGuide()
  },

  onResize() {
    this._pauseLoginGuide({ preserveTimer: true })
    if (this.data.showLoginGuide) this.setData({ loginGuideReady: false })
    this.measureNavigation(() => {
      if (this._alive && this._visible && this.data.showLoginGuide) this._positionLoginGuide()
    })
  },
}

module.exports = { DISMISSED_KEY, loginGuideLayout, guestLoginGuideMethods }

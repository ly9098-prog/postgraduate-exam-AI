const auth = require('../../utils/auth')
const api = require('../../utils/api')
const storage = require('../../utils/storage')
const privacy = require('../../utils/privacy')
const config = require('../../config')
const { getNavigationMetrics } = require('../../utils/navigation')
const { createLoginResume } = require('../../utils/launch-resume')
const { userId: resumeOwnerId } = require('../../utils/launch-session-store')

Page({
  data: {
    loading: false,
    error: '',
    showDevLogin: false,
    agreed: false,
    entryPending: true,
    navHeight: 88,
    statusBarHeight: 20,
    navContentHeight: 44,
    navRightPadding: 116,
  },

  _pageDestroyed: false,
  _pageVisible: false,
  _homeRedirectTimer: null,
  _pendingHomeRedirect: false,
  _homeRedirectResolving: false,
  _loginAttemptSeq: 0,
  _loginCancelled: false,

  onLoad(options) {
    this._launchResume = createLoginResume()
    const redirect = String((options && options.redirect) || '')
    this._sourceUrl = /^\/(?:pages|subpackages)\/[a-zA-Z0-9/_-]+(?:\?[^#]*)?$/.test(redirect) &&
      !redirect.startsWith('/pages/login/login') ? redirect : ''
    this._pageDestroyed = false
    // onLoad is immediately followed by onShow on first entry. Mark the page
    // visible now so a direct-login redirect can be scheduled without relying
    // on lifecycle ordering details across base-library versions.
    this._pageVisible = true
    this.setData(getNavigationMetrics())

    // Automatic auth invalidation intentionally preserves the current privacy
    // acceptance. Restore that state into the checkbox so returning users are
    // not asked to consent again after a token refresh/login boundary.
    const agreed = privacy.hasAcceptedCurrentPrivacy()
    this._returnOnSuccess = this._hasReturnTarget()
    this.setData({ agreed, entryPending: auth.isLoggedIn() && agreed })

    // 同步检查：token 有效且协议已同意时延迟跳转
    if (this._tryDirectRedirect()) return
    // No stored session: show the login form. wx.login is only called from an
    // explicit tap so first-time visitors can browse the home page instead.
    this._safeSetData({ entryPending: false })
  },

  onShow() {
    this._pageVisible = true
    if (this._pendingHomeRedirect) {
      this._scheduleHomeRedirect(0)
    }
  },

  onHide() {
    this._pageVisible = false
    this._clearHomeRedirectTimer()
  },

  onUnload() {
    this._pageDestroyed = true
    this._pageVisible = false
    this._pendingHomeRedirect = false
    this._loginAttemptSeq += 1
    this._clearHomeRedirectTimer()
  },

  _safeSetData(data, callback) {
    if (this._pageDestroyed) return
    this.setData(data, callback)
  },

  _hasReturnTarget() {
    try {
      const pages = getCurrentPages()
      return Boolean(pages && pages.length > 1)
    } catch (_) {
      return false
    }
  },

  _clearHomeRedirectTimer() {
    if (this._homeRedirectTimer) {
      clearTimeout(this._homeRedirectTimer)
      this._homeRedirectTimer = null
    }
  },

  _scheduleHomeRedirect(delayMs = 0) {
    if (this._pageDestroyed) return
    this._pendingHomeRedirect = true
    this._clearHomeRedirectTimer()
    if (!this._pageVisible) return
    this._safeSetData({ entryPending: true })

    this._homeRedirectTimer = setTimeout(async () => {
      this._homeRedirectTimer = null
      if (this._pageDestroyed || !this._pageVisible) return

      // A delayed redirect must re-check the session. This prevents a stale
      // timer from entering Home after auth/privacy state changed meanwhile.
      if (!auth.isLoggedIn() || !privacy.hasAcceptedCurrentPrivacy()) {
        this._pendingHomeRedirect = false
        this._safeSetData({ entryPending: false })
        return
      }

      await this._redirectAfterLogin()
    }, Math.max(0, Number(delayMs) || 0))
  },

  async _redirectAfterLogin() {
    if (this._homeRedirectResolving) return
    this._homeRedirectResolving = true
    const owner = resumeOwnerId()
    const attemptSeq = this._loginAttemptSeq
    if (!await auth.checkAndRefreshToken()) {
      this._homeRedirectResolving = false
      this._pendingHomeRedirect = false
      this._safeSetData({ entryPending: false })
      return
    }
    if (this._pageDestroyed || !this._pageVisible) {
      this._homeRedirectResolving = false
      return
    }
    if (owner !== resumeOwnerId() || attemptSeq !== this._loginAttemptSeq ||
      !auth.isLoggedIn() || !privacy.hasAcceptedCurrentPrivacy()) {
      this._homeRedirectResolving = false
      this._pendingHomeRedirect = false
      this._safeSetData({ entryPending: false })
      return
    }
    if (this._returnOnSuccess && this._hasReturnTarget()) {
      // Arrived from a page's cancellable login prompt: return there instead of
      // replaying the write action the user originally attempted.
      this._pendingHomeRedirect = false
      this._homeRedirectResolving = false
      this._safeSetData({ entryPending: false })
      wx.navigateBack({ fail: () => wx.reLaunch({ url: '/pages/home/home' }) })
      return
    }
    if (this._sourceUrl) {
      this._pendingHomeRedirect = false
      this._homeRedirectResolving = false
      wx.reLaunch({
        url: this._sourceUrl,
        fail: () => this._safeSetData({
          entryPending: false, loading: false, error: '返回页面失败，可暂不登录返回首页',
        }),
      })
      return
    }
    let target
    try {
      target = await this._launchResume.resolve()
    } catch (_) {
      this._pendingHomeRedirect = false
      this._safeSetData({ entryPending: false, loading: false, error: '进入页面失败，请重试' })
      return
    } finally {
      this._homeRedirectResolving = false
    }
    if (this._pageDestroyed || !this._pageVisible) return
    if (attemptSeq !== this._loginAttemptSeq) {
      if (!this.data.loading) this._scheduleHomeRedirect(0)
      return
    }
    if (!target || !auth.isLoggedIn() || !privacy.hasAcceptedCurrentPrivacy() ||
      owner !== resumeOwnerId()) {
      this._pendingHomeRedirect = false
      this._safeSetData({ entryPending: false })
      return
    }
    this._pendingHomeRedirect = false
    wx.reLaunch({
      url: target,
      success: () => this._launchResume.complete(),
      fail: () => {
        if (this._pageDestroyed) return
        this._safeSetData({ entryPending: false, loading: false, error: '进入页面失败，请重试' })
      },
    })
  },

  /** 同步检查 storage 中的 token 和协议同意状态 */
  _tryDirectRedirect() {
    const token = storage.get(storage.KEYS.TOKEN)
    const rawExpiresAt = storage.get(storage.KEYS.TOKEN_EXPIRES_AT)
    if (!token) return false
    // 协议版本已升级或未同意 → 留在登录页
    if (!privacy.hasAcceptedCurrentPrivacy()) {
      return false
    }
    if (rawExpiresAt === null || rawExpiresAt === undefined || rawExpiresAt === '') {
      this._scheduleHomeRedirect(100)
      return true
    }

    const expiresAt = api.normalizeExpiresAt(rawExpiresAt)
    if (!expiresAt) {
      // Corrupted/legacy expiry metadata should go through the async validator
      // instead of being treated as an indefinitely valid token.
      return false
    }
    const tte = expiresAt - Math.floor(api.now() / 1000)
    if (tte > 86400) {
      this._scheduleHomeRedirect(100)
      return true
    }
    // Token 需要刷新 → 走 async 链路
    return false
  },

  _isCurrentAttempt(attemptSeq) {
    return !this._pageDestroyed && attemptSeq === this._loginAttemptSeq
  },

  _savePrivacyAfterLogin() {
    try {
      privacy.savePrivacyAcceptance(['user_agreement', 'privacy_policy', 'ai_service'])
    } catch (_) {
      // Authentication + consent must be committed as one logical state. If
      // strict storage of the consent record fails (for example storage is
      // full), roll back the auth session rather than leaving a hidden logged-
      // in state while the page reports a login failure.
      storage.clearSession({ preservePrivacyAcceptance: true, includeDebugSnapshots: false })
      throw new Error('协议确认记录保存失败，请清理存储空间后重试')
    }
  },

  _loginErrorMessage(error, fallback) {
    if (error && typeof error.message === 'string' && error.message.trim()) {
      return error.message.trim()
    }
    const errMsg = error && typeof error.errMsg === 'string' ? error.errMsg : ''
    if (errMsg.indexOf('login') >= 0 || errMsg.indexOf('network') >= 0) {
      return '微信登录失败，请检查网络后重试'
    }
    return fallback || '登录失败，请稍后重试'
  },

  onGuestBrowse() {
    if (this._pageDestroyed) return
    this._loginCancelled = true
    this._pendingHomeRedirect = false
    this._clearHomeRedirectTimer()
    this._loginAttemptSeq += 1
    try {
      if (this._hasReturnTarget()) {
        wx.navigateBack({ fail: () => wx.reLaunch({ url: '/pages/home/home' }) })
      } else {
        wx.reLaunch({ url: '/pages/home/home' })
      }
    } catch (_) {
      wx.reLaunch({ url: '/pages/home/home' })
    }
  },

  onAgreementChange(e) {
    if (this.data.loading) return
    const values = e && e.detail && Array.isArray(e.detail.value) ? e.detail.value : []
    const agreed = values.includes('agreed')
    this.setData({ agreed })
    // 不在此处保存协议记录，仅在登录成功后保存
  },

  openAgreement(e) {
    const type = e && e.currentTarget && e.currentTarget.dataset
      ? e.currentTarget.dataset.type
      : ''
    const pathMap = {
      user: '/pages/agreement/user',
      privacy: '/pages/agreement/privacy',
      ai: '/pages/agreement/ai',
    }
    const url = pathMap[type]
    if (!url) return
    wx.navigateTo({ url })
  },

  ensureAgreementAccepted() {
    if (this.data.agreed) return true
    wx.showToast({ title: '请先阅读并同意相关协议', icon: 'none' })
    return false
  },

  async onWechatLogin() {
    if (this._pageDestroyed || this.data.loading) return
    if (!this.ensureAgreementAccepted()) return
    const attemptSeq = ++this._loginAttemptSeq
    this._loginCancelled = false
    this._safeSetData({ loading: true, error: '' })
    try {
      await auth.wechatLogin({ shouldCommit: () => !this._loginCancelled })
      if (this._loginCancelled) return
      // auth.wechatLogin commits auth first, so always finish the consent commit
      // (or roll auth back) before any lifecycle-based early return.
      this._savePrivacyAfterLogin()
      api.resetRedirecting()
      if (!this._isCurrentAttempt(attemptSeq)) return
      this._safeSetData({ loading: false })
      this._scheduleHomeRedirect(0)
    } catch (e) {
      if (!this._isCurrentAttempt(attemptSeq)) return
      this._safeSetData({ entryPending: false, error: this._loginErrorMessage(e, '登录失败，请稍后重试') })
    } finally {
      if (this._isCurrentAttempt(attemptSeq) && this.data.loading) {
        this._safeSetData({ loading: false })
      }
    }
  },

  async onDevLogin() {
    if (this._pageDestroyed || this.data.loading) return
    if (!this.ensureAgreementAccepted()) return
    const attemptSeq = ++this._loginAttemptSeq
    this._safeSetData({ loading: true, error: '' })
    try {
      const loginResult = await wx.login()
      if (!this._isCurrentAttempt(attemptSeq)) return
      const code = loginResult && loginResult.code
      if (!code) throw new Error('微信登录失败，请重试')

      const data = await api.post('/auth/login', { code })
      if (!this._isCurrentAttempt(attemptSeq)) return
      auth.loginDirect(data.access_token, data.user, data.expires_at, data.refresh_token)
      this._savePrivacyAfterLogin()
      api.resetRedirecting()
      this._safeSetData({ loading: false })
      this._scheduleHomeRedirect(0)
    } catch (e) {
      if (!this._isCurrentAttempt(attemptSeq)) return
      this._safeSetData({ entryPending: false, error: this._loginErrorMessage(e, '开发模式登录失败，请确保后端已启动') })
    } finally {
      if (this._isCurrentAttempt(attemptSeq) && this.data.loading) {
        this._safeSetData({ loading: false })
      }
    }
  },
})

const auth = require('../../utils/auth')
const api = require('../../utils/api')
const storage = require('../../utils/storage')
const privacy = require('../../utils/privacy')
const config = require('../../config')
const { getNavigationMetrics } = require('../../utils/navigation')

Page({
  data: {
    loading: false,
    error: '',
    showDevLogin: false,
    agreed: false,
    navHeight: 88,
    statusBarHeight: 20,
    navContentHeight: 44,
    navRightPadding: 116,
  },

  _pageDestroyed: false,
  _pageVisible: false,
  _homeRedirectTimer: null,
  _pendingHomeRedirect: false,
  _loginAttemptSeq: 0,

  onLoad() {
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
    this.setData({ agreed })

    // 同步检查：token 有效且协议已同意时延迟跳转
    if (this._tryDirectRedirect()) return
    this._autoLogin()
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

    this._homeRedirectTimer = setTimeout(() => {
      this._homeRedirectTimer = null
      if (this._pageDestroyed || !this._pageVisible) return

      // A delayed redirect must re-check the session. This prevents a stale
      // timer from entering Home after auth/privacy state changed meanwhile.
      if (!auth.isLoggedIn() || !privacy.hasAcceptedCurrentPrivacy()) {
        this._pendingHomeRedirect = false
        return
      }

      this._pendingHomeRedirect = false
      wx.reLaunch({
        url: '/pages/home/home',
        fail: () => {
          if (this._pageDestroyed) return
          this._safeSetData({
            loading: false,
            error: '进入首页失败，请重试',
          })
        },
      })
    }, Math.max(0, Number(delayMs) || 0))
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

  /**
   * 自动登录（async 链路）
   * Phase 1 — 有持久化 token → checkAndRefreshToken 成功后跳转
   * Phase 2 — 无 token / 失效 → 静默 wx.login（最多 2 次）
   */
  async _autoLogin() {
    if (this._pageDestroyed) return
    var attemptSeq = ++this._loginAttemptSeq
    this._safeSetData({ loading: true, error: "" })
    if (await this._tryExistingSession(attemptSeq)) return
    if (!this.data.agreed) { this._safeSetData({ loading: false }); return }
    await this._tryWxLoginLoop(attemptSeq)
  },

  async _tryExistingSession(attemptSeq) {
    if (!auth.isLoggedIn()) return false
    var ok = await auth.checkAndRefreshToken()
    if (!this._isCurrentAttempt(attemptSeq)) return true
    if (ok && privacy.hasAcceptedCurrentPrivacy()) {
      this._safeSetData({ loading: false })
      this._scheduleHomeRedirect(0)
      return true
    }
    if (!auth.isLoggedIn()) { this._safeSetData({ loading: false }); return true }
    return false
  },

  async _tryWxLoginLoop(attemptSeq) {
    var lastErr
    for (var i = 0; i < 2; i++) {
      if (i > 0) await new Promise(function(resolve) { setTimeout(resolve, 600) })
      if (!this._isCurrentAttempt(attemptSeq)) return
      try {
        await this._performWxLoginAttempt(attemptSeq)
        return
      } catch (e) {
        lastErr = e
        if (config.DEV) console.warn("[AUTH] Phase 2 attempt " + (i + 1) + " FAILED:", (e && (e.errMsg || e.message)) || "")
      }
    }
    if (!this._isCurrentAttempt(attemptSeq)) return
    this._safeSetData({ error: this._loginErrorMessage(lastErr, "自动登录失败，请点击微信登录重试"), showDevLogin: !!config.DEV, loading: false })
  },

  async _performWxLoginAttempt(attemptSeq) {
    if (config.DEV) console.log("[AUTH] Phase 2 attempt: wx.login")
    var loginResult = await wx.login()
    if (!this._isCurrentAttempt(attemptSeq)) return
    var code = loginResult && loginResult.code
    if (!code) throw new Error("微信登录失败，请重试")
    if (config.DEV) console.log("[AUTH] Phase 2: code received, calling POST /auth/login")
    var data = await api.post("/auth/login", { code: code })
    if (!this._isCurrentAttempt(attemptSeq)) return
    if (config.DEV) console.log("[AUTH] Phase 2: login succeeded, storing token")
    auth.loginDirect(data.access_token, data.user, data.expires_at, data.refresh_token)
    this._savePrivacyAfterLogin()
    api.resetRedirecting()
    var valid = await auth.checkAndRefreshToken()
    if (!this._isCurrentAttempt(attemptSeq)) return
    if (!valid) {
      storage.clearSession({ preservePrivacyAcceptance: true, includeDebugSnapshots: false })
      throw new Error("登录状态校验失败，请重试")
    }
    this._safeSetData({ loading: false })
    this._scheduleHomeRedirect(0)
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
    this._safeSetData({ loading: true, error: '' })
    try {
      await auth.wechatLogin()
      // auth.wechatLogin commits auth first, so always finish the consent commit
      // (or roll auth back) before any lifecycle-based early return.
      this._savePrivacyAfterLogin()
      api.resetRedirecting()
      if (!this._isCurrentAttempt(attemptSeq)) return
      this._safeSetData({ loading: false })
      this._scheduleHomeRedirect(0)
    } catch (e) {
      if (!this._isCurrentAttempt(attemptSeq)) return
      this._safeSetData({ error: this._loginErrorMessage(e, '登录失败，请稍后重试') })
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
      this._safeSetData({ error: this._loginErrorMessage(e, '开发模式登录失败，请确保后端已启动') })
    } finally {
      if (this._isCurrentAttempt(attemptSeq) && this.data.loading) {
        this._safeSetData({ loading: false })
      }
    }
  },
})

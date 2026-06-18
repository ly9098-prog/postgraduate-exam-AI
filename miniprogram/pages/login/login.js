const auth = require('../../utils/auth')
const api = require('../../utils/api')
const storage = require('../../utils/storage')

Page({
  data: {
    loading: false,
    error: '',
    showDevLogin: false,
    agreed: false,
  },

  onLoad() {
    this._diagAuth()
    // 同步直连跳转：不经过 async 链路，onLoad 中读取 storage → 立即 redirect
    if (this._tryDirectRedirect()) return
    // async 链路继续尝试
    this._autoLogin()
  },

  /** 同步诊断 */
  _diagAuth() {
    const token = storage.get(storage.KEYS.TOKEN)
    const expiresAt = storage.get(storage.KEYS.TOKEN_EXPIRES_AT)
    const persist = storage.get('_login_persist_test')
    console.log('[AUTH_DIAG] _login_persist_test:', persist)
    console.log('[AUTH_DIAG] token:', token ? token.slice(0, 20) + '…' : null)
    console.log('[AUTH_DIAG] token_expires_at:', expiresAt)
    console.log('[AUTH_DIAG] refresh_token:', !!storage.get(storage.KEYS.REFRESH_TOKEN))
    console.log('[AUTH_DIAG] isLoggedIn():', auth.isLoggedIn())
    if (token && expiresAt) {
      const tte = expiresAt - Math.floor(Date.now() / 1000)
      console.log('[AUTH_DIAG] timeToExpiry:', tte + 's', tte > 86400 ? '(valid)' : '(needs refresh)')
    }
  },

  /** 同步直连跳转：不经过任何 async API，直接检查 storage 后 redirect */
  _tryDirectRedirect() {
    const token = storage.get(storage.KEYS.TOKEN)
    const expiresAt = storage.get(storage.KEYS.TOKEN_EXPIRES_AT)
    if (!token) return false
    // 无过期信息 → 视为有效
    if (!expiresAt) {
      console.log('[AUTH_DIAG] direct redirect: no expires_at')
      wx.redirectTo({ url: '/pages/home/home' })
      return true
    }
    const tte = expiresAt - Math.floor(Date.now() / 1000)
    if (tte > 86400) {
      console.log('[AUTH_DIAG] direct redirect: token valid, tte=' + tte + 's')
      wx.redirectTo({ url: '/pages/home/home' })
      return true
    }
    // Token 需要刷新 → 走 _autoLogin async 链路
    return false
  },

  /**
   * 自动登录（async 链路）
   * Phase 1 — 有持久化 token → checkAndRefreshToken 成功后跳转
   * Phase 2 — 无 token / 失效 → 静默 wx.login（最多 2 次）
   */
  async _autoLogin() {
    this.setData({ loading: true })

    if (auth.isLoggedIn()) {
      console.log('[AUTH_DIAG] Phase 1: calling checkAndRefreshToken')
      const ok = await auth.checkAndRefreshToken()
      console.log('[AUTH_DIAG] Phase 1: result =', ok)
      if (ok) {
        this.setData({ loading: false })
        wx.redirectTo({ url: '/pages/home/home' })
        return
      }
    }

    let lastErr
    for (let i = 0; i < 2; i++) {
      if (i > 0) await new Promise(r => setTimeout(r, 600))
      try {
        console.log('[AUTH_DIAG] Phase 2 attempt ' + (i + 1) + ': wx.login')
        const { code } = await wx.login()
        console.log('[AUTH_DIAG] Phase 2: code received, calling POST /auth/login')
        const data = await api.post('/auth/login', { code })
        console.log('[AUTH_DIAG] Phase 2: login succeeded, storing token')
        auth.loginDirect(data.access_token, data.user, data.expires_at, data.refresh_token)
        api.resetRedirecting()

        const valid = await auth.checkAndRefreshToken()
        if (!valid) throw new Error('new token rejected by ensureValidToken')

        this.setData({ loading: false })
        wx.redirectTo({ url: '/pages/home/home' })
        return
      } catch (e) {
        lastErr = e
        const msg = (e && (e.errMsg || e.message || JSON.stringify(e))) || ''
        console.warn('[AUTH_DIAG] Phase 2 attempt ' + (i + 1) + ' FAILED:', msg)
      }
    }

    const errMsg = (lastErr && (lastErr.errMsg || lastErr.message || JSON.stringify(lastErr))) || '自动登录失败'
    const config = require('../../config')
    this.setData({
      error: '[auto] ' + errMsg,
      showDevLogin: config.DEV || true,
      loading: false,
    })
  },

  onAgreementChange(e) {
    this.setData({ agreed: e.detail.value.includes('agreed') })
  },

  openAgreement(e) {
    const { type } = e.currentTarget.dataset
    const pathMap = {
      user: '/pages/agreement/user',
      privacy: '/pages/agreement/privacy',
      ai: '/pages/agreement/ai',
    }
    wx.navigateTo({ url: pathMap[type] })
  },

  ensureAgreementAccepted() {
    if (this.data.agreed) return true
    wx.showToast({ title: '请先阅读并同意相关协议', icon: 'none' })
    return false
  },

  async onWechatLogin() {
    if (!this.ensureAgreementAccepted()) return
    this.setData({ loading: true, error: '' })
    try {
      await auth.wechatLogin()
      api.resetRedirecting()
      wx.redirectTo({ url: '/pages/home/home' })
    } catch (e) {
      const msg = e.message || (typeof e === 'string' ? e : '登录失败')
      this.setData({ error: msg })
    } finally {
      this.setData({ loading: false })
    }
  },

  async onDevLogin() {
    if (!this.ensureAgreementAccepted()) return
    // 开发模式：绕过微信登录，使用固定 dev code
    this.setData({ loading: true, error: '' })
    try {
      const { code } = await wx.login()
      const data = await api.post('/auth/login', { code })
      auth.loginDirect(data.access_token, data.user, data.expires_at, data.refresh_token)
      api.resetRedirecting()
      wx.redirectTo({ url: '/pages/home/home' })
    } catch (e) {
      this.setData({ error: '开发模式登录失败，请确保后端已启动' })
    } finally {
      this.setData({ loading: false })
    }
  },
})

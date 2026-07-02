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
    // 同步检查：token 有效时延迟跳转（setTimeout 确保冷启动 onLoad 后导航不被吞）
    if (this._tryDirectRedirect()) return
    this._autoLogin()
  },

  /** 同步检查 storage 中的 token，有效则延迟跳转 */
  _tryDirectRedirect() {
    const token = storage.get(storage.KEYS.TOKEN)
    const expiresAt = storage.get(storage.KEYS.TOKEN_EXPIRES_AT)
    if (!token) return false
    if (!expiresAt) {
      setTimeout(() => wx.reLaunch({ url: '/pages/home/home' }), 100)
      return true
    }
    const tte = expiresAt - Math.floor(Date.now() / 1000)
    if (tte > 86400) {
      setTimeout(() => wx.reLaunch({ url: '/pages/home/home' }), 100)
      return true
    }
    // Token 需要刷新 → 走 async 链路
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
      const ok = await auth.checkAndRefreshToken()
      if (ok) {
        this.setData({ loading: false })
        wx.redirectTo({ url: '/pages/home/home' })
        return
      }
    }

    // Phase 2 requires agreement — don't silently login without user consent
    if (!this.data.agreed) {
      this.setData({ loading: false })
      return
    }

    let lastErr
    for (let i = 0; i < 2; i++) {
      if (i > 0) await new Promise(r => setTimeout(r, 600))
      try {
        console.log('[AUTH] Phase 2 attempt ' + (i + 1) + ': wx.login')
        const { code } = await wx.login()
        console.log('[AUTH] Phase 2: code received, calling POST /auth/login')
        const data = await api.post('/auth/login', { code })
        console.log('[AUTH] Phase 2: login succeeded, storing token')
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
        console.warn('[AUTH] Phase 2 attempt ' + (i + 1) + ' FAILED:', msg)
      }
    }

    const errMsg = (lastErr && (lastErr.errMsg || lastErr.message || JSON.stringify(lastErr))) || '自动登录失败'
    const config = require('../../config')
    this.setData({
      error: '[auto] ' + errMsg,
      showDevLogin: !!config.DEV,
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

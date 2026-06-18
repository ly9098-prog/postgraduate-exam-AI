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
    this._diagPersistence()
    this._autoLogin()
  },

  // —— 诊断：检测 storage 是否跨进程存活 ——
  _diagPersistence() {
    const persist = storage.get('_login_persist_test')
    console.log('[AUTH_DIAG] _login_persist_test:', persist)
    console.log('[AUTH_DIAG] has token:', !!storage.get(storage.KEYS.TOKEN))
    if (!persist) {
      console.log('[AUTH_DIAG] ⚠️  persist marker missing — storage may have been cleared')
    }
  },

  /**
   * 自动登录：两阶段策略
   * Phase 1 — 有持久化 token → 验签后直接跳转
   * Phase 2 — 无 token / token 失效 → 静默 wx.login 重建 session
   *           最多重试 2 次（冷启动 wx.login 短暂不可用）
   *           成功后验证新 token 再跳转，避免 home 页 API 401 回流
   */
  async _autoLogin() {
    this.setData({ loading: true })

    // Phase 1: 已有持久化 token
    if (auth.isLoggedIn()) {
      const ok = await auth.checkAndRefreshToken()
      if (ok) {
        this.setData({ loading: false })
        wx.redirectTo({ url: '/pages/home/home' })
        return
      }
    }

    // Phase 2: 静默 wx.login（最多 2 次，覆盖冷启动 JSSDK 未就绪）
    let lastErr
    for (let i = 0; i < 2; i++) {
      if (i > 0) await new Promise(r => setTimeout(r, 600))
      try {
        const { code } = await wx.login()
        const data = await api.post('/auth/login', { code })
        auth.loginDirect(data.access_token, data.user, data.expires_at, data.refresh_token)
        api.resetRedirecting()

        // 验证新 token 能被 checkAndRefreshToken 接受
        const valid = await auth.checkAndRefreshToken()
        if (!valid) throw new Error('new token rejected by ensureValidToken')

        this.setData({ loading: false })
        wx.redirectTo({ url: '/pages/home/home' })
        return
      } catch (e) {
        lastErr = e
        const msg = (e && (e.message || e.errMsg || typeof e === 'string' ? e : '')) || ''
        console.warn('[AUTH_DIAG] Phase 2 attempt ' + (i + 1) + ' failed:', msg)
      }
    }

    // 全部失败 → 显示登录页 + 错误详情
    const errMsg = (lastErr && (lastErr.message || lastErr.errMsg || JSON.stringify(lastErr))) || '自动登录失败'
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

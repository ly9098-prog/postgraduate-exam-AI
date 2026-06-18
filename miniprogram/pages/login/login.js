const auth = require('../../utils/auth')
const api = require('../../utils/api')

Page({
  data: {
    loading: false,
    error: '',
    showDevLogin: false,
    agreed: false,
  },

  onLoad() {
    // 无论是否有 token，都尝试自动登录
    // 有 token → 验证后跳转；无 token → 静默 wx.login 重建 session
    this._autoLogin()
  },

  async _autoLogin() {
    this.setData({ loading: true })

    // Phase 1: 有已持久化的 token → 尝试验证
    if (auth.isLoggedIn()) {
      const ok = await auth.checkAndRefreshToken()
      if (ok) {
        this.setData({ loading: false })
        wx.redirectTo({ url: '/pages/home/home' })
        return
      }
    }

    // Phase 2: 无 token 或 token 不可用 → 静默 wx.login 重建 session
    // 效果同 admin web：登录一次长期有效，不再每次手动登录
    try {
      const { code } = await wx.login()
      const data = await api.post('/auth/login', { code })
      auth.loginDirect(data.access_token, data.user, data.expires_at, data.refresh_token)
      api.resetRedirecting()
      wx.redirectTo({ url: '/pages/home/home' })
    } catch (e) {
      const config = require('../../config')
      this.setData({ showDevLogin: config.DEV === true, loading: false, error: '' })
    }
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

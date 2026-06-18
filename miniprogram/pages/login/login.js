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
    // 已有 token 则尝试验证并自动进入首页
    if (auth.isLoggedIn()) {
      this._tryAutoLogin()
      return
    }
    // 仅开发环境显示开发者模式入口
    const config = require('../../config')
    this.setData({ showDevLogin: config.DEV === true })
  },

  async _tryAutoLogin() {
    this.setData({ loading: true })
    const ok = await auth.checkAndRefreshToken()
    if (ok) {
      this.setData({ loading: false })
      wx.redirectTo({ url: '/pages/home/home' })
      return
    }
    // 首次失败，延迟重试（覆盖冷启动网络延迟）
    await new Promise(r => setTimeout(r, 2000))
    const ok2 = await auth.checkAndRefreshToken()
    this.setData({ loading: false })
    if (ok2) {
      wx.redirectTo({ url: '/pages/home/home' })
    }
    // 仍失败则留在登录页，显示正常登录按钮
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

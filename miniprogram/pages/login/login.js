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
    this._diagStorage()
    if (auth.isLoggedIn()) {
      this._tryAutoLogin()
      return
    }
    // 冷启动 storage 可能延迟就绪（部分真机环境），延迟重试一次
    this._retryTimer = setTimeout(() => {
      if (auth.isLoggedIn()) {
        console.log('[AUTH_DIAG] delayed check: token found, redirecting')
        wx.redirectTo({ url: '/pages/home/home' })
      }
    }, 500)
    const config = require('../../config')
    this.setData({ showDevLogin: config.DEV === true })
  },

  onUnload() {
    if (this._retryTimer) clearTimeout(this._retryTimer)
  },

  _diagStorage() {
    const info = wx.getStorageInfoSync()
    const keys = info.keys || []
    console.log('[AUTH_DIAG] storage keys:', JSON.stringify(keys))
    console.log('[AUTH_DIAG] has token key:', keys.includes('token'))
    console.log('[AUTH_DIAG] has token_expires_at:', keys.includes('token_expires_at'))
    console.log('[AUTH_DIAG] has refresh_token:', keys.includes('refresh_token'))
    console.log('[AUTH_DIAG] isLoggedIn():', auth.isLoggedIn())
  },

  async _tryAutoLogin() {
    this.setData({ loading: true })
    console.log('[AUTH_DIAG] _tryAutoLogin: attempt 1')
    const ok = await auth.checkAndRefreshToken()
    console.log('[AUTH_DIAG] _tryAutoLogin: attempt 1 result:', ok)
    if (ok) {
      this.setData({ loading: false })
      wx.redirectTo({ url: '/pages/home/home' })
      return
    }
    await new Promise(r => setTimeout(r, 2000))
    console.log('[AUTH_DIAG] _tryAutoLogin: attempt 2')
    const ok2 = await auth.checkAndRefreshToken()
    console.log('[AUTH_DIAG] _tryAutoLogin: attempt 2 result:', ok2)
    this.setData({ loading: false })
    if (ok2) {
      wx.redirectTo({ url: '/pages/home/home' })
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

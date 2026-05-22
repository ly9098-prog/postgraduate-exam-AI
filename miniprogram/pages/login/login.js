const auth = require('../../utils/auth')
const api = require('../../utils/api')

Page({
  data: {
    loading: false,
    error: '',
    showDevLogin: false,
  },

  onLoad() {
    // 已有 token 则自动登录进首页
    if (auth.isLoggedIn()) {
      wx.redirectTo({ url: '/pages/home/home' })
      return
    }
    // 开发环境显示"跳过微信登录"入口
    const config = require('../../config')
    this.setData({ showDevLogin: !config.BASE_URL.includes('your-domain') })
  },

  async onWechatLogin() {
    this.setData({ loading: true, error: '' })
    try {
      await auth.wechatLogin()
      wx.redirectTo({ url: '/pages/home/home' })
    } catch (e) {
      const msg = e.message || (typeof e === 'string' ? e : '登录失败')
      this.setData({ error: msg })
    } finally {
      this.setData({ loading: false })
    }
  },

  async onDevLogin() {
    // 开发模式：绕过微信登录，使用固定 dev code
    this.setData({ loading: true, error: '' })
    try {
      const { code } = await wx.login()
      const data = await api.post('/auth/login', { code })
      auth.loginDirect(data.access_token, data.user)
      wx.redirectTo({ url: '/pages/home/home' })
    } catch (e) {
      this.setData({ error: '开发模式登录失败，请确保后端已启动' })
    } finally {
      this.setData({ loading: false })
    }
  },
})

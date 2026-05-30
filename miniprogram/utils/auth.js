const api = require('./api')
const storage = require('./storage')
const { KEYS } = storage

async function wechatLogin() {
  // 1. wx.login 获取临时 code
  const { code } = await wx.login()
  if (!code) throw new Error('微信登录失败，请重试')

  // 2. 发送 code 到后端换 token
  const data = await api.post('/auth/login', { code })
  storage.set(KEYS.TOKEN, data.access_token)
  storage.set(KEYS.USER, data.user)
  return data.user
}

function logout() {
  storage.remove(KEYS.TOKEN)
  storage.remove(KEYS.USER)
}

function getToken() {
  return storage.get(KEYS.TOKEN)
}

function isLoggedIn() {
  return !!storage.get(KEYS.TOKEN)
}

function getUser() {
  return storage.get(KEYS.USER)
}

function isAdmin() {
  const user = getUser() || {}
  return user.is_admin === true || user.role === 'admin' || user.role_name === 'admin'
}

function requireAdminAccess(message = '仅管理员可访问') {
  if (isAdmin()) return true
  wx.showToast({ title: message, icon: 'none' })
  return false
}

// 开发模式：直接设置 token（不经过 wx.login）
function loginDirect(token, user) {
  storage.set(KEYS.TOKEN, token)
  storage.set(KEYS.USER, user)
}

module.exports = { wechatLogin, loginDirect, logout, getToken, isLoggedIn, getUser, isAdmin, requireAdminAccess }

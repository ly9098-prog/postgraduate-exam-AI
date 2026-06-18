const api = require('./api')
const storage = require('./storage')
const config = require('../config')
const { KEYS } = storage

function normalizeUser(user) {
  const normalized = user || {}
  const role = normalized.role || normalized.role_name || ''
  const permissions = Array.isArray(normalized.permissions) ? normalized.permissions : []
  return {
    ...normalized,
    role,
    role_name: normalized.role_name || role,
    is_admin: normalized.is_admin === true || role === 'admin' || role === 'super_admin' || permissions.includes('import:write'),
    permissions,
  }
}

async function syncCurrentUser() {
  if (!getToken()) return null
  const user = normalizeUser(await api.get('/users/me'))
  storage.set(KEYS.USER, user)
  return user
}

async function wechatLogin() {
  const { code } = await wx.login()
  if (!code) throw new Error('微信登录失败，请重试')
  const data = await api.post('/auth/login', { code })
  const user = normalizeUser(data.user)
  storage.set(KEYS.TOKEN, data.access_token)
  storage.set(KEYS.TOKEN_EXPIRES_AT, data.expires_at)
  storage.set(KEYS.REFRESH_TOKEN, data.refresh_token)
  storage.set(KEYS.USER, user)
  return user
}

function logout() {
  storage.remove(KEYS.TOKEN)
  storage.remove(KEYS.TOKEN_EXPIRES_AT)
  storage.remove(KEYS.REFRESH_TOKEN)
  storage.remove(KEYS.USER)
}

function getToken() {
  return storage.get(KEYS.TOKEN)
}

function isLoggedIn() {
  return !!storage.get(KEYS.TOKEN)
}

function getUser() {
  return normalizeUser(storage.get(KEYS.USER))
}

function isAdmin() {
  if (config.DEV === true) return true
  const user = getUser()
  return user.is_admin === true || user.role === 'admin' || user.role === 'super_admin' || user.role_name === 'admin' || user.role_name === 'super_admin'
}

function requireAdminAccess(message = '仅管理员可访问') {
  if (isAdmin()) return true
  wx.showToast({ title: message, icon: 'none' })
  return false
}

// 开发模式：直接设置 token（不经过 wx.login）
function loginDirect(token, user, expiresAt, refreshToken) {
  storage.set(KEYS.TOKEN, token)
  if (expiresAt) storage.set(KEYS.TOKEN_EXPIRES_AT, expiresAt)
  if (refreshToken) storage.set(KEYS.REFRESH_TOKEN, refreshToken)
  storage.set(KEYS.USER, normalizeUser(user))
}

/**
 * 检查并刷新登录态（供 App 生命周期调用）
 * 无 token 或无需刷新则静默跳过，不弹错误
 */
async function checkAndRefreshToken() {
  if (!getToken()) return false
  try {
    return await api.ensureValidToken()
  } catch {
    return false
  }
}

module.exports = { wechatLogin, loginDirect, logout, getToken, isLoggedIn, getUser, isAdmin, requireAdminAccess, syncCurrentUser, normalizeUser, checkAndRefreshToken }

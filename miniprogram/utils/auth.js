const api = require('./api')
const storage = require('./storage')
const config = require('../config')
const privacy = require('./privacy')
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
  storage.set(KEYS.TOKEN_EXPIRES_AT, api.normalizeExpiresAt(data.expires_at))
  storage.set(KEYS.REFRESH_TOKEN, data.refresh_token)
  storage.set(KEYS.USER, user)
  return user
}

function logout() {
  // 清除认证信息
  storage.remove(KEYS.TOKEN)
  storage.remove(KEYS.TOKEN_EXPIRES_AT)
  storage.remove(KEYS.REFRESH_TOKEN)
  storage.remove(KEYS.USER)

  // 清除用户业务缓存，防止跨账号数据串用
  var businessKeys = [
    'lastPracticeResult',
    'wrong_detail_nav',
    'pomodoro_running_state',
    'pomodoro_pause',
    'pomodoro_free_pause',
    'pomodoro_completion',
    'pomodoro_break',
    'pomodoro_confirm_pause',
    'pomodoro_pause_adjustment',
    'pomodoro_font_size',
    'pomodoro_anim_idx',
    'home_today_goal_total',
  ]
  for (var bi = 0; bi < businessKeys.length; bi++) {
    try { wx.removeStorageSync(businessKeys[bi]) } catch (_) {}
  }

  // 清除调试快照
  try {
    var allKeys = wx.getStorageInfoSync().keys || []
    for (var ki = 0; ki < allKeys.length; ki++) {
      if (allKeys[ki].indexOf('debug_snapshot:') === 0) {
        wx.removeStorageSync(allKeys[ki])
      }
    }
  } catch (_) {}

  privacy.clearPrivacyAcceptance()
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
  const user = getUser()
  return user.is_admin === true || user.role === 'admin' || user.role === 'super_admin' || user.role_name === 'admin' || user.role_name === 'super_admin'
}

function requireAdminAccess(message = '仅管理员可访问') {
  if (!isLoggedIn()) {
    wx.showToast({ title: '请先登录', icon: 'none' })
    setTimeout(() => wx.reLaunch({ url: '/pages/login/login' }), 500)
    return false
  }
  if (isAdmin()) return true
  wx.showToast({ title: message, icon: 'none' })
  return false
}

function redirectToLogin() {
  wx.reLaunch({ url: '/pages/login/login' })
}

// 开发模式：直接设置 token（不经过 wx.login）
function loginDirect(token, user, expiresAt, refreshToken) {
  storage.set(KEYS.TOKEN, token)
  if (expiresAt) storage.set(KEYS.TOKEN_EXPIRES_AT, api.normalizeExpiresAt(expiresAt))
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

module.exports = { wechatLogin, loginDirect, logout, getToken, isLoggedIn, getUser, isAdmin, requireAdminAccess, redirectToLogin, syncCurrentUser, normalizeUser, checkAndRefreshToken }

const api = require('./api')
const storage = require('./storage')
const config = require('../config')
const privacy = require('./privacy')
const { KEYS } = storage

function normalizeUser(user) {
  const normalized = user || {}
  const role = normalized.role || normalized.role_name || ''
  const permissions = Array.isArray(normalized.permissions) ? normalized.permissions : []
  const nickname = typeof normalized.nickname === 'string' ? normalized.nickname.trim() : ''
  return {
    ...normalized,
    nickname: nickname || null,
    profile_completed: normalized.profile_completed === true || !!nickname,
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

function isProfileCompleted(user) {
  const normalized = normalizeUser(user)
  return normalized.profile_completed === true
}

async function updateProfile({ nickname, avatarPath } = {}) {
  const normalizedNickname = typeof nickname === 'string' ? nickname.trim().replace(/\s+/g, ' ') : ''
  if (!normalizedNickname) throw new Error('请输入昵称')

  // 头像接口本身会返回最新 UserResponse。保留该响应中的 avatar_url，
  // 避免随后更新昵称时遇到缓存/并发响应而把刚换的新头像又覆盖成旧地址。
  let avatarUser = null
  if (avatarPath) {
    avatarUser = normalizeUser(await api.uploadFile('/users/me/avatar', avatarPath, { name: 'file', timeout: 30000 }))
  }

  const nicknameUser = normalizeUser(await api.put('/users/me', { nickname: normalizedNickname }))
  const user = normalizeUser({
    ...(avatarUser || {}),
    ...(nicknameUser || {}),
    avatar_url: (avatarUser && avatarUser.avatar_url) || (nicknameUser && nicknameUser.avatar_url) || null,
  })
  storage.setStrict(KEYS.USER, user)
  return user
}

/** 严格写入认证信息，失败时回滚并抛出异常 */
function saveAuthSession(data, user) {
  try {
    storage.setStrict(KEYS.TOKEN, data.access_token)
    storage.setStrict(
      KEYS.TOKEN_EXPIRES_AT,
      api.normalizeExpiresAt(data.expires_at)
    )
    storage.setStrict(KEYS.REFRESH_TOKEN, data.refresh_token)
    storage.setStrict(KEYS.USER, user || {})
  } catch (error) {
    // 回滚已写入的认证信息
    try { wx.removeStorageSync(KEYS.TOKEN) } catch (_) {}
    try { wx.removeStorageSync(KEYS.TOKEN_EXPIRES_AT) } catch (_) {}
    try { wx.removeStorageSync(KEYS.REFRESH_TOKEN) } catch (_) {}
    try { wx.removeStorageSync(KEYS.USER) } catch (_) {}
    throw new Error('登录信息保存失败，请清理存储空间后重试')
  }
}

async function wechatLogin() {
  const { code } = await wx.login()
  if (!code) throw new Error('微信登录失败，请重试')
  const data = await api.post('/auth/login', { code })
  const user = normalizeUser(data.user)
  saveAuthSession(data, user)
  return user
}

/** 退出登录：撤销服务端 token + 清除本地所有会话数据 */
async function logout() {
  // 1. 优先尝试撤销服务端 Refresh Token（fire-and-forget，不阻塞本地清理）
  try {
    await api.post('/auth/logout')
  } catch (_) {
    // 服务端退出非必须（Token 自身过期后自动失效），静默忽略
  }

  // 2. 清除本地所有会话数据
  storage.clearSession({ preservePrivacyAcceptance: false, includeDebugSnapshots: true })

  // 3. 清除协议同意记录，下次启动需重新同意
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
  saveAuthSession(
    {
      access_token: token,
      expires_at: expiresAt,
      refresh_token: refreshToken || '',
    },
    normalizeUser(user)
  )
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

module.exports = {
  wechatLogin,
  loginDirect,
  logout,
  getToken,
  isLoggedIn,
  getUser,
  isAdmin,
  requireAdminAccess,
  redirectToLogin,
  syncCurrentUser,
  normalizeUser,
  isProfileCompleted,
  updateProfile,
  checkAndRefreshToken,
}

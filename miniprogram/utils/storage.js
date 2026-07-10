const KEYS = {
  TOKEN: 'token',
  USER: 'user',
  TOKEN_EXPIRES_AT: 'token_expires_at',
  REFRESH_TOKEN: 'refresh_token',
}

/** 业务缓存键列表 — 会话切换或注销时需清除 */
const BUSINESS_CACHE_KEYS = [
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

/** 始终保留的键（会话清理时不受影响） */
const PROTECTED_KEYS = [
  'privacy_acceptance',
]

function get(key) {
  try {
    return wx.getStorageSync(key)
  } catch {
    return null
  }
}

function set(key, value) {
  try {
    wx.setStorageSync(key, value)
  } catch (e) {
    console.error('Storage set error:', e)
  }
}

/** 严格写入：失败时抛出错误，用于认证信息和协议记录等关键数据 */
function setStrict(key, value) {
  wx.setStorageSync(key, value)
}

function remove(key) {
  try {
    wx.removeStorageSync(key)
  } catch {
    // ignore
  }
}

/**
 * 统一会话清理：清除认证信息 + 业务缓存，可选保留协议同意记录。
 *
 * @param {object} [options]
 * @param {boolean} [options.preservePrivacyAcceptance=false] 为 true 时不清除协议同意记录
 * @param {boolean} [options.includeDebugSnapshots=true] 是否清除调试快照
 *
 * 调用场景：
 * - 手动退出（preservePrivacyAcceptance=false）
 * - Token 失效/401 自动清理（preservePrivacyAcceptance=true）
 * - 切换账号（preservePrivacyAcceptance=true）
 * - 账号注销（preservePrivacyAcceptance=false）
 */
function clearSession(options) {
  var opts = options || {}
  var preservePrivacy = opts.preservePrivacyAcceptance === true

  // 1. 清除认证信息
  remove(KEYS.TOKEN)
  remove(KEYS.TOKEN_EXPIRES_AT)
  remove(KEYS.REFRESH_TOKEN)
  remove(KEYS.USER)

  // 2. 清除业务缓存
  for (var bi = 0; bi < BUSINESS_CACHE_KEYS.length; bi++) {
    remove(BUSINESS_CACHE_KEYS[bi])
  }

  // 3. 清除 AI 诊断本地缓存（以 ai_ 或 aiCache 开头的键）
  try {
    var allKeys = wx.getStorageInfoSync().keys || []
    for (var ki = 0; ki < allKeys.length; ki++) {
      var key = allKeys[ki]
      // 跳过受保护的键
      if (preservePrivacy && PROTECTED_KEYS.indexOf(key) >= 0) continue
      if (key.indexOf('ai_') === 0 || key.indexOf('aiCache') === 0 || key.indexOf('ai_diagnosis') === 0) {
        remove(key)
      }
    }
  } catch (_) {}

  // 4. 清除调试快照
  if (opts.includeDebugSnapshots !== false) {
    try {
      var keys2 = wx.getStorageInfoSync().keys || []
      for (var ki2 = 0; ki2 < keys2.length; ki2++) {
        if (keys2[ki2].indexOf('debug_snapshot:') === 0) {
          remove(keys2[ki2])
        }
      }
    } catch (_) {}
  }
}

module.exports = { KEYS, get, set, setStrict, remove, clearSession, BUSINESS_CACHE_KEYS, PROTECTED_KEYS }

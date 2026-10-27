const KEYS = {
  TOKEN: 'token',
  USER: 'user',
  TOKEN_EXPIRES_AT: 'token_expires_at',
  REFRESH_TOKEN: 'refresh_token',
}

/** 业务缓存键列表 — 会话切换或注销时需清除 */
const BUSINESS_CACHE_KEYS = [
  'lastPracticeResult',
  'practice_recent_subjects_v1',
  'wrong_detail_nav',
  'pomodoro_running_state',
  'pomodoro_pause',
  'pomodoro_free_pause',
  'pomodoro_completion',
  'pomodoro_break',
  'pomodoro_confirm_pause',
  'pomodoro_pause_adjustment',
  'pomodoro_pending_sync',
  'pomodoro_unknown_start',
  'pomodoro_terminal_conflict',
  'pomodoro_font_size',
  'pomodoro_anim_idx',
  'home_today_goal_total',
]

/** 始终保留的键（会话清理时不受影响） */
const PROTECTED_KEYS = [
  'privacy_acceptance',
]

const SESSION_DYNAMIC_KEY_PREFIXES = [
  'ai_',
  'aiCache',
  'ai_diagnosis',
  'practice_pending_submission_v1:',
  'exam_attempt_pending_v1:',
  'exam_attempt_pending_v2:',
  'exam_attempt_pending_v3:',
  'review_today_draft_v1:',
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

  // 3. 清除动态会话缓存（AI 诊断 + 待确认刷题提交）
  try {
    var allKeys = wx.getStorageInfoSync().keys || []
    for (var ki = 0; ki < allKeys.length; ki++) {
      var key = allKeys[ki]
      // 跳过受保护的键
      if (preservePrivacy && PROTECTED_KEYS.indexOf(key) >= 0) continue
      if (SESSION_DYNAMIC_KEY_PREFIXES.some(prefix => key.indexOf(prefix) === 0)) {
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

function ownerFingerprint() {
  const user = get(KEYS.USER) || {}
  const raw = user.id || user.user_id || user.uid || user.openid || user.username || user.nickname || user.nickName || ''
  return raw ? String(raw) : 'anonymous'
}

module.exports = {
  KEYS,
  BUSINESS_CACHE_KEYS,
  PROTECTED_KEYS,
  SESSION_DYNAMIC_KEY_PREFIXES,
  get,
  set,
  setStrict,
  remove,
  clearSession,
  ownerFingerprint,
}

// ═══════════════════════════════════════════════
// 动画分包加载管理 — 按需加载，不在启动时主动下载
// ═══════════════════════════════════════════════

var _ANIM_LOADED = false
var _ANIM_CALLBACKS = []
var _animLoadPromise = null

function onAnimReady(cb) {
  if (_ANIM_LOADED) return cb()
  _ANIM_CALLBACKS.push(cb)
}

/** 按需加载动画分包，避免重复并发加载 */
function loadRewardAnimationPackage() {
  if (_animLoadPromise) return _animLoadPromise
  if (_ANIM_LOADED) {
    _animLoadPromise = Promise.resolve()
    return _animLoadPromise
  }
  _animLoadPromise = new Promise(function (resolve) {
    if (typeof wx.loadSubpackage === 'function') {
      wx.loadSubpackage({
        root: 'subpackages/animation',
        success: function () { _onAnimLoaded(); resolve() },
        fail: function () { _animLoadPromise = null; resolve() }, // 不影响主流程，同时允许后续重试
      })
    } else {
      // 基础库版本过低，不支持 wx.loadSubpackage，静默跳过
      resolve()
    }
  })
  return _animLoadPromise
}

function _onAnimLoaded() {
  _ANIM_LOADED = true
  _ANIM_CALLBACKS.forEach(function (cb) { try { cb() } catch (_) {} })
  _ANIM_CALLBACKS = []
}

/**
 * Get safe (non-sensitive) page route info for error diagnostics.
 * Skips: token, user answers, full questions, AI analysis, PII.
 */
function _safePageInfo() {
  try {
    var pages = getCurrentPages()
    if (!pages || !pages.length) return ''
    var top = pages[pages.length - 1]
    if (!top) return ''
    var route = top.route || ''
    var info = 'route:' + route
    var opts = top.options || {}
    var paramKeys = Object.keys(opts)
    if (paramKeys.length > 0) {
      info += ' paramCount:' + paramKeys.length
    }
    return info
  } catch (_) {
    return ''
  }
}

/**
 * Strip sensitive data from error log context.
 */
function _sanitizeStack(stack) {
  if (!stack || typeof stack !== 'string') return ''
  var lines = stack.split('\n')
  if (lines.length > 5) {
    lines = lines.slice(0, 5)
    lines.push('    (...truncated)')
  }
  return lines.join('\n')
}

App({
  onLaunch() {
    // 不在启动时加载动画分包，改为在首次播放时由 getApp().loadRewardAnimationPackage() 按需加载
    this._startPreviewTempFileCleanup()
  },

  loadRewardAnimationPackage: loadRewardAnimationPackage,

  onShow() {
    this._tryRestoreLogin()
    this._startPreviewTempFileCleanup()
  },

  onHide() {
    this._stopPreviewTempFileCleanup()
  },

  onError(err) {
    try {
      var sdkVersion = ''
      try { sdkVersion = wx.getSystemInfoSync ? (wx.getSystemInfoSync().SDKVersion || '') : '' } catch (_) {}
      var ctx = [
        'type:runtime',
        'SDK:' + sdkVersion,
        _safePageInfo(),
      ].filter(Boolean).join(' | ')
      var msg = typeof err === 'string' ? err : (err && err.message) || ''
      console.error('[GLOBAL_ERROR]', ctx, msg)
      if (err && err.stack) {
        console.error('[GLOBAL_ERROR] stack:', _sanitizeStack(err.stack))
      }
    } catch (_) {}
  },

  onUnhandledRejection(err) {
    try {
      var reason = err && (err.reason || err.message || err)
      var sdkVersion = ''
      try { sdkVersion = wx.getSystemInfoSync ? (wx.getSystemInfoSync().SDKVersion || '') : '' } catch (_) {}
      var ctx = [
        'type:rejection',
        'SDK:' + sdkVersion,
        _safePageInfo(),
      ].filter(Boolean).join(' | ')
      var msg = typeof reason === 'string' ? reason : (reason && reason.message) || ''
      console.error('[GLOBAL_UNHANDLED]', ctx, msg)
    } catch (_) {}
  },

  onPageNotFound(res) {
    try {
      console.warn('[PAGE_NOT_FOUND]', res && res.path)
    } catch (_) {}
    // Safe redirect: never redirect to the same path to avoid loops
    wx.reLaunch({ url: '/pages/home/home' })
  },

  getGlobalData() {
    return this._globalData || (this._globalData = {})
  },

  _globalData: null,
  _previewTempCleanupTimer: null,

  _startPreviewTempFileCleanup() {
    const manager = require('./utils/preview-temp-files')
    manager.cleanupIfDue().catch(function(err) {
      console.warn('[PREVIEW_TEMP_CLEANUP] cleanup failed', err && (err.errMsg || err.message || err))
    })

    if (this._previewTempCleanupTimer) return
    this._previewTempCleanupTimer = setInterval(function() {
      manager.cleanupIfDue({ force: true }).catch(function(err) {
        console.warn('[PREVIEW_TEMP_CLEANUP] scheduled cleanup failed', err && (err.errMsg || err.message || err))
      })
    }, manager.CLEANUP_INTERVAL_MS)
  },

  _stopPreviewTempFileCleanup() {
    if (!this._previewTempCleanupTimer) return
    clearInterval(this._previewTempCleanupTimer)
    this._previewTempCleanupTimer = null
  },

  async _tryRestoreLogin() {
    const storage = require('./utils/storage')
    const auth = require('./utils/auth')
    if (!storage.get(storage.KEYS.TOKEN)) return
    try {
      await auth.checkAndRefreshToken()
    } catch (_) {}
  },
})

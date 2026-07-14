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

App({
  onLaunch() {
    // 不在启动时加载动画分包，改为在首次播放时由 getApp().loadRewardAnimationPackage() 按需加载
  },

  loadRewardAnimationPackage: loadRewardAnimationPackage,

  onShow() {
    this._tryRestoreLogin()
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

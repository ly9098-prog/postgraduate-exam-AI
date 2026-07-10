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
    if (typeof wx.loadSubPackage === 'function') {
      wx.loadSubPackage({
        root: 'subpackages/animation',
        success: function () { _onAnimLoaded(); resolve() },
        fail: function () { resolve() }, // 不影响主流程
      })
    } else if (typeof wx.preloadSubPackage === 'function') {
      wx.preloadSubPackage({
        root: 'subpackages/animation',
        success: function () { _onAnimLoaded(); resolve() },
        fail: function () { resolve() },
      })
    } else {
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
    this._preWarmSession()
  },

  loadRewardAnimationPackage: loadRewardAnimationPackage,

  onShow() {
    this._tryRestoreLogin()
  },

  /** 提前预热：无 token 时提前 wx.login，避免 login 页冷启动时首次调用失败 */
  async _preWarmSession() {
    const storage = require('./utils/storage')
    if (storage.get(storage.KEYS.TOKEN)) return
    try { await wx.login() } catch (_) {}
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

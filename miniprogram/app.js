var _ANIM_LOADED = false
var _ANIM_CALLBACKS = []

function onAnimReady(cb) {
  if (_ANIM_LOADED) return cb()
  _ANIM_CALLBACKS.push(cb)
}

function tryLoadAnimSubpkg() {
  // 1) 优先 wx.loadSubPackage
  if (typeof wx.loadSubPackage === 'function') {
    wx.loadSubPackage({
      root: 'subpackages/animation',
      success: function () { _onAnimLoaded() },
      fail: function () { _navFallback() },
    })
    return
  }
  // 2) 尝试 preloadSubPackage（新版 API 名可能有变）
  if (typeof wx.preloadSubPackage === 'function') {
    wx.preloadSubPackage({
      root: 'subpackages/animation',
      success: function () { _onAnimLoaded() },
      fail: function () { _navFallback() },
    })
    return
  }
  // 3) 兜底：导航到分包页面强制加载
  _navFallback()
}

function _navFallback() {
  wx.navigateTo({
    url: '/subpackages/animation/animation-index/animation-index',
    complete: function () {
      setTimeout(function () {
        wx.navigateBack({ delta: 1 })
        _onAnimLoaded()
      }, 50)
    },
  })
}

function _onAnimLoaded() {
  _ANIM_LOADED = true
  _ANIM_CALLBACKS.forEach(function (cb) { try { cb() } catch (_) {} })
  _ANIM_CALLBACKS = []
}

App({
  onLaunch() {
    tryLoadAnimSubpkg()
    // 在 login 页面加载前尽可能提前建立 session
    this._preWarmSession()
  },

  onShow() {
    this._tryRestoreLogin()
  },

  /** 提前预热：无 token 时提前 wx.login，避免 login 页冷启动时首次调用失败 */
  async _preWarmSession() {
    const storage = require('./utils/storage')
    if (storage.get(storage.KEYS.TOKEN)) return
    // 仅跑一次 wx.login 让 WeChat JSSDK 内部状态就绪
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

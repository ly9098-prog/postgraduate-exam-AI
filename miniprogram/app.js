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
    // 不自动跳转首页，让 login 页面处理登录态
    // 避免 token 过期时闪现首页后跳登录页

    // 预加载动画分包
    tryLoadAnimSubpkg()
  },
})

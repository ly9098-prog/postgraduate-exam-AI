App({
  onLaunch() {
    // 不自动跳转首页，让 login 页面处理登录态
    // 避免 token 过期时闪现首页后跳登录页

    // 预加载动画分包，多种 API 名兼容
    try {
      var fn = wx.preloadSubPackage || wx.loadSubPackage
      if (typeof fn === 'function') {
        fn({ root: 'subpackages/animation', fail: function () {} })
      }
    } catch (_) {}
  },
})

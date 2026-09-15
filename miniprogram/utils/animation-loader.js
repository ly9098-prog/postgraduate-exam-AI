// ═══════════════════════════════════════════════════════════
// 动画分包异步加载器 — 跨分包模块必须使用异步 require
// ═══════════════════════════════════════════════════════════

var _lottieModule = null
var _lottieData = null
var _loadingPromise = null

function _loadLottieLoaderAsync() {
  return new Promise(function (resolve) {
    var settled = false
    function finish(mod) {
      if (settled) return
      settled = true
      resolve(mod || null)
    }

    try {
      // 微信分包异步化：优先使用 Promise 风格，避免同步跨包 require
      if (require && typeof require.async === 'function') {
        require.async('../subpackages/animation/lottie-loader.js')
          .then(function (mod) { finish(mod) })
          .catch(function () { finish(null) })
        return
      }

      // 兼容支持 callback 风格异步 require 的基础库。
      // 不再退回同步 require；不支持分包异步化时直接使用静态兜底动画。
      var immediate = require(
        '../subpackages/animation/lottie-loader.js',
        function (mod) { finish(mod) },
        function () { finish(null) }
      )
      // 极旧运行时可能忽略 callback 参数而直接返回模块；若发生则正常接住。
      if (immediate) finish(immediate)
    } catch (_) {
      finish(null)
    }
  })
}

/**
 * 异步获取动画分包入口。多次调用共享同一 Promise；失败后允许后续重试。
 */
function loadAnimationPackage() {
  if (_lottieModule) return Promise.resolve(_lottieModule)
  if (_loadingPromise) return _loadingPromise

  _loadingPromise = _loadLottieLoaderAsync().then(function (mod) {
    _lottieModule = mod || null
    if (!_lottieModule) _loadingPromise = null
    return _lottieModule
  }).catch(function () {
    _loadingPromise = null
    _lottieModule = null
    return null
  })

  return _loadingPromise
}

function getLottieModule() {
  if (!_lottieModule) return null
  try { return _lottieModule.getModule() } catch (_) { return null }
}

function getRewardData() {
  if (!_lottieModule) return null
  if (!_lottieData) {
    try { _lottieData = _lottieModule.getRewardData ? _lottieModule.getRewardData() : null } catch (_) {}
  }
  return _lottieData
}

function getLoadingData() {
  if (!_lottieModule) return null
  try { return _lottieModule.getLoadingData ? _lottieModule.getLoadingData() : null } catch (_) {}
  return null
}

module.exports = {
  loadAnimationPackage: loadAnimationPackage,
  getLottieModule: getLottieModule,
  getRewardData: getRewardData,
  getLoadingData: getLoadingData,
}

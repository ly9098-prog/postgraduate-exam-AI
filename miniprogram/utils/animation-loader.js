// ═══════════════════════════════════════════════════════════
// 动画分包异步加载器 — 避免主包组件同步 require 分包文件
// ═══════════════════════════════════════════════════════════

var _lottieModule = null
var _lottieData = null
var _loadingPromise = null

/**
 * 触发动画分包加载 → 分包就绪后 require lottie-loader → 缓存 module + data
 * 多次调用共享同一 Promise，仅一次真实加载
 */
function loadAnimationPackage() {
  if (_loadingPromise) return _loadingPromise

  _loadingPromise = new Promise(function (resolve) {
    try {
      var app = getApp()
      if (app && app.loadRewardAnimationPackage) {
        app.loadRewardAnimationPackage().then(function () {
          resolve()
        }).catch(function () {
          resolve() // 不影响主流程
        })
      } else {
        resolve()
      }
    } catch (_) {
      resolve()
    }
  }).then(function () {
    // 分包已就绪，同步 require 不再触发警告
    try {
      _lottieModule = require('../../subpackages/animation/lottie-loader.js')
    } catch (_) {
      _lottieModule = null
    }
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

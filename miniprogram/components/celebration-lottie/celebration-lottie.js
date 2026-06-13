// 庆祝动效组件 —— Lottie 优先 → CSS 降级（两级保障，无 Canvas 2D 中间层）
// 使用方式:
//   <celebration-lottie show="{{showCelebration}}"
//     type="practice"   // practice | steady | excellent | final | combo | group | focus
//     title="高质量挑战完成"
//     detail="答对 5/5 题 · 正确率 100%"
//     motto="继续保持，薄弱点会越来越少"
//     reward-text="专注星光 +5"
//     duration="{{2800}}"
//     bind:done="onCelebrationDone" />
//
// Lottie 动画 .js 文件位于 /assets/lottie/
// Lottie 路径：canvas 上播放 Lottie + cover-view 文字叠加（cover-view 可渲染在原生 canvas 上方）
// CSS 降级路径：纯 CSS 粒子 + 徽章 + view 文字叠加（无原生 canvas，无层级问题）

// ── 类型 → Lottie JS 映射（静态 require，单个失败不影响其他类型）──
// 微信小程序打包器对 require() 做静态依赖分析 —— 动态拼接的路径无法被识别，
// 必须用字面量字符串写出每个 require，打包器才会将对应文件打入分包。
function _loadLottieMap() {
  var map = {}

  var trophyMod = null
  var successMod = null
  var celebrationMod = null
  var fireworksMod = null
  var medalMod = null
  var studyMod = null

  try { trophyMod = require('../../assets/lottie/trophy.js') } catch (_) {}
  try { successMod = require('../../assets/lottie/success-check.js') } catch (_) {}
  try { celebrationMod = require('../../assets/lottie/celebration.js') } catch (_) {}
  try { fireworksMod = require('../../assets/lottie/fireworks.js') } catch (_) {}
  try { medalMod = require('../../assets/lottie/medal.js') } catch (_) {}
  try { studyMod = require('../../assets/lottie/study.js') } catch (_) {}

  if (trophyMod) map.excellent = trophyMod
  if (successMod) { map.practice = successMod; map.steady = successMod }
  if (celebrationMod) map.final = celebrationMod
  if (fireworksMod) map.combo = fireworksMod
  if (medalMod) map.group = medalMod
  if (studyMod) map.focus = studyMod

  if (Object.keys(map).length === 0) {
    console.warn('[celebration-lottie] 所有 Lottie 动画加载失败，将使用 CSS 降级')
    return null
  }
  return map
}
var LOTTIE_MAP = _loadLottieMap()

// ── 尝试加载 lottie-miniprogram（静态 require 多路径回退）──
var lottieModule = null
try { lottieModule = require('lottie-miniprogram') } catch (_) {}
if (!lottieModule) {
  try { lottieModule = require('../../miniprogram_npm/lottie-miniprogram/index') } catch (_) {}
}

// lottie-miniprogram 内部通过 createTag('canvas') 动态创建 canvas 用于图层合成，
// 但微信小程序不支持 document.createElement，返回 mock 对象导致动画无法渲染。
// 该问题在基础库提供 createOffscreenCanvas 或库适配后可解决，届时改为 true 即可启用 Lottie。
var ENABLE_LOTTIE = false

Component({
  properties: {
    show: { type: Boolean, value: false },
    type: { type: String, value: 'steady' },
    title: { type: String, value: '' },
    detail: { type: String, value: '' },
    motto: { type: String, value: '' },
    rewardText: { type: String, value: '' },
    progressText: { type: String, value: '' },
    growthLevel: { type: String, value: '' },
    growthLevelPct: { type: Number, value: 0 },
    growthDesc: { type: String, value: '' },
    duration: { type: Number, value: 2800 },
  },

  data: {
    canvasReady: false,
    visible: false,
    showContent: false,
    useLottie: false,
  },

  observers: {
    show: function (val) {
      if (val) {
        this.setData({ visible: true, showContent: false })
        this._startAnimation()
        if (this._contentTimer) clearTimeout(this._contentTimer)
        this._contentTimer = setTimeout(function () {
          this.setData({ showContent: true })
        }.bind(this), 320)
        if (this._timer) clearTimeout(this._timer)
        this._timer = setTimeout(function () {
          this._stopAnimation()
          if (this._lottieAnim) {
            try { this._lottieAnim.destroy() } catch (_) {}
            this._lottieAnim = null
          }
          this.setData({ visible: false, showContent: false })
          this.triggerEvent('done')
        }.bind(this), this.data.duration)
      }
    },
  },

  lifetimes: {
    attached: function () {
      this._lottieAnim = null
      this._reducedMotion = false
      // 判断能否走 Lottie 渲染（lottie-miniprogram 可用 + 至少有一种动画数据 + 功能开关开启）
      this._canLottie = !!(ENABLE_LOTTIE && lottieModule && LOTTIE_MAP)
      try {
        var sysInfo = wx.getSystemInfoSync()
        if (sysInfo && sysInfo.reduceMotion === true) {
          this._reducedMotion = true
        }
      } catch (_) {}
    },
    ready: function () {
      if (this._canLottie) {
        // 先用 setData 将 canvas 渲染到 DOM，再在回调中获取节点初始化
        this.setData({ canvasReady: true }, function () {
          this._initCanvas()
        }.bind(this))
      }
      // 否则不初始化 canvas，WXML 走 wx:else → CSS 降级
    },
    detached: function () {
      this._stopAnimation()
      if (this._timer) clearTimeout(this._timer)
      if (this._contentTimer) clearTimeout(this._contentTimer)
      if (this._lottieAnim) {
        try { this._lottieAnim.destroy() } catch (_) {}
        this._lottieAnim = null
      }
    },
  },

  methods: {
    _initCanvas: function () {
      var self = this
      var query = this.createSelectorQuery()
      query.select('#celebration-canvas')
        .fields({ node: true, size: true })
        .exec(function (res) {
          if (!res || !res[0] || !res[0].node) {
            // canvas 节点获取失败，降级到 CSS
            self.setData({ canvasReady: false })
            return
          }
          var canvas = res[0].node
          var ctx = canvas.getContext('2d')
          var dpr = wx.getSystemInfoSync().pixelRatio || 2
          var width = res[0].width
          var height = res[0].height
          canvas.width = width * dpr
          canvas.height = height * dpr
          ctx.scale(dpr, dpr)
          self._canvas = canvas
          self._ctx = ctx

          try {
            lottieModule.setup(canvas)
            self.setData({ useLottie: true })
          } catch (_) {
            // Lottie.setup 失败，降级到 CSS
            self.setData({ canvasReady: false })
          }
        })
    },

    _startAnimation: function () {
      if (this._reducedMotion) return
      if (this.data.useLottie && this._canLottie) {
        this._startLottie()
      }
      // Lottie 不可用时不需要额外操作，CSS 降级的动画由 WXSS @keyframes 驱动
    },

    /* ──── Lottie 渲染 ──── */

    _startLottie: function () {
      var self = this
      var animationData = LOTTIE_MAP && LOTTIE_MAP[this.data.type]
      if (!animationData) {
        console.warn('[celebration-lottie] 无 "' + this.data.type + '" 类型的 Lottie 数据，降级到 CSS')
        this.setData({ canvasReady: false, useLottie: false })
        return
      }
      try {
        this._lottieAnim = lottieModule.loadAnimation({
          loop: false,
          autoplay: true,
          animationData: animationData,
          rendererSettings: {
            context: this._ctx,
            clearCanvas: true,
          },
          canvas: this._canvas,
        })
      } catch (e) {
        console.error('[celebration-lottie] Lottie.loadAnimation 失败，降级到 CSS', e)
        this._lottieAnim = null
        this.setData({ canvasReady: false, useLottie: false })
      }
    },

    _stopAnimation: function () {
      if (this._lottieAnim) {
        try { this._lottieAnim.destroy() } catch (_) {}
        this._lottieAnim = null
      }
    },

    onTap: function () {
      if (this._timer) clearTimeout(this._timer)
      if (this._contentTimer) clearTimeout(this._contentTimer)
      this._stopAnimation()
      this.setData({ visible: false, showContent: false })
      this.triggerEvent('done')
    },
  },
})

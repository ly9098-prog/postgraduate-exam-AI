var LOTTIE_DATA_CACHE = null
var LOTTIE_MODULE_CACHE = undefined
var LOTTIE_DISABLED = false

function loadLottieData() {
  if (LOTTIE_DATA_CACHE !== null) return LOTTIE_DATA_CACHE

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

  LOTTIE_DATA_CACHE = Object.keys(map).length ? map : false
  return LOTTIE_DATA_CACHE
}

function loadLottieModule() {
  if (LOTTIE_DISABLED) return null
  if (LOTTIE_MODULE_CACHE !== undefined) return LOTTIE_MODULE_CACHE

  var mod = null
  try { mod = require('lottie-miniprogram') } catch (_) {}
  if (!mod) {
    try { mod = require('../../miniprogram_npm/lottie-miniprogram/index') } catch (_) {}
  }

  LOTTIE_MODULE_CACHE = mod || null
  return LOTTIE_MODULE_CACHE
}

function getDevicePixelRatio() {
  try {
    if (wx.getWindowInfo) return wx.getWindowInfo().pixelRatio || 2
  } catch (_) {}
  return 2
}

function getSystemInfo() {
  try {
    if (wx.getDeviceInfo && wx.getAppBaseInfo) {
      var deviceInfo = wx.getDeviceInfo() || {}
      var appBaseInfo = wx.getAppBaseInfo() || {}
      return {
        platform: (deviceInfo.platform || '').toLowerCase(),
        SDKVersion: appBaseInfo.SDKVersion || '',
      }
    }
    if (wx.getSystemInfoSync) return wx.getSystemInfoSync() || {}
  } catch (_) {}
  return {}
}

function compareVersion(v1, v2) {
  var a = String(v1 || '').split('.')
  var b = String(v2 || '').split('.')
  var len = Math.max(a.length, b.length)
  for (var i = 0; i < len; i += 1) {
    var n1 = parseInt(a[i] || '0', 10)
    var n2 = parseInt(b[i] || '0', 10)
    if (n1 > n2) return 1
    if (n1 < n2) return -1
  }
  return 0
}

function isReducedMotionEnabled() {
  try {
    if (wx.getSystemSetting) return wx.getSystemSetting().reduceMotion === true
  } catch (_) {}
  return false
}

function getFallbackGlyph(type) {
  if (type === 'excellent' || type === 'final') return 'star'
  if (type === 'combo') return 'fire'
  if (type === 'focus') return 'focus'
  return 'check'
}

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
    gifSrc: { type: String, value: '' },
    pngSrc: { type: String, value: '' },
    enableLottie: { type: Boolean, value: true },
  },

  data: {
    visible: false,
    showContent: false,
    mode: 'hidden',
    canvasReady: false,
    useLottie: false,
    fallbackGlyph: 'check',
  },

  observers: {
    show: function (val) {
      if (val) {
        this._show()
      } else {
        this._hide(false)
      }
    },
    type: function (val) {
      this.setData({ fallbackGlyph: getFallbackGlyph(val) })
    },
  },

  lifetimes: {
    attached: function () {
      this._lottieAnim = null
      this._canvas = null
      this._ctx = null
      this._timer = null
      this._contentTimer = null
      this._canvasTimer = null
      this._pausedByPage = false
      this._reducedMotion = isReducedMotionEnabled()
      this._canUseCanvas = false
      this._canUseLottie = false
      this.setData({ fallbackGlyph: getFallbackGlyph(this.data.type) })
      this._detectSupport()
    },
    detached: function () {
      this._clearTimers()
      this._destroyLottie()
    },
  },

  pageLifetimes: {
    show: function () {
      if (this._pausedByPage) {
        this._pausedByPage = false
        this._resumeAnimation()
      }
    },
    hide: function () {
      if (this.data.visible) {
        this._pausedByPage = true
        this._pauseAnimation()
      }
    },
  },

  methods: {
    _detectSupport: function () {
      var info = getSystemInfo()
      var baseOk = compareVersion(info.SDKVersion, '2.9.0') >= 0
      var lottieModule = null
      var lottieData = null

      if (this.data.enableLottie && baseOk) {
        try { lottieModule = loadLottieModule() } catch (_) { lottieModule = null }
        try { lottieData = loadLottieData() } catch (_) { lottieData = null }
      }

      this._lottieModule = lottieModule
      this._lottieData = lottieData
      this._canUseCanvas = !!baseOk
      this._canUseLottie = !!(this.data.enableLottie && baseOk && lottieModule && lottieData)
    },

    _resolveMode: function () {
      if (this._reducedMotion) return this.data.pngSrc ? 'png' : 'hidden'
      if (this._canUseLottie) return 'lottie'
      if (this.data.gifSrc) return 'gif'
      if (this.data.pngSrc) return 'png'
      return 'static'
    },

    _show: function () {
      this._clearTimers()
      this._destroyLottie()
      this._detectSupport()

      var mode = this._resolveMode()
      var nextData = {
        visible: true,
        showContent: false,
        mode: mode,
        useLottie: false,
        canvasReady: mode === 'lottie',
        fallbackGlyph: getFallbackGlyph(this.data.type),
      }
      this.setData(nextData, function () {
        if (mode === 'lottie') this._initCanvas()
      }.bind(this))

      this._contentTimer = setTimeout(function () {
        if (this.data.visible) this.setData({ showContent: true })
      }.bind(this), 320)

      this._timer = setTimeout(function () {
        this._hide(true)
      }.bind(this), this.data.duration)
    },

    _initCanvas: function () {
      if (!this._canUseLottie || !this.data.visible) return
      var self = this
      var query = this.createSelectorQuery()
      query.select('#animated-view-canvas')
        .fields({ node: true, size: true })
        .exec(function (res) {
          try {
            if (!res || !res[0] || !res[0].node) {
              self._fallbackFromLottie()
              return
            }
            var canvas = res[0].node
            var ctx = canvas.getContext && canvas.getContext('2d')
            if (!ctx) {
              self._fallbackFromLottie()
              return
            }
            var dpr = getDevicePixelRatio()
            var width = res[0].width || 1
            var height = res[0].height || 1
            canvas.width = width * dpr
            canvas.height = height * dpr
            ctx.scale(dpr, dpr)
            self._canvas = canvas
            self._ctx = ctx
            self._lottieModule.setup(canvas)
            self.setData({ useLottie: true })
            self._startLottie()
          } catch (_) {
            self._fallbackFromLottie()
          }
        })
    },

    _startLottie: function () {
      if (!this._canUseLottie || !this._canvas || !this._ctx) return
      var animationData = this._lottieData && this._lottieData[this.data.type]
      if (!animationData) {
        this._fallbackFromLottie()
        return
      }
      try {
        this._lottieAnim = this._lottieModule.loadAnimation({
          loop: false,
          autoplay: true,
          animationData: animationData,
          rendererSettings: {
            context: this._ctx,
            clearCanvas: true,
          },
          canvas: this._canvas,
        })
      } catch (_) {
        this._lottieAnim = null
        this._fallbackFromLottie()
      }
    },

    _fallbackFromLottie: function () {
      this._destroyLottie()
      var mode = this.data.gifSrc ? 'gif' : (this.data.pngSrc ? 'png' : 'static')
      this.setData({ mode: mode, canvasReady: false, useLottie: false })
    },

    _pauseAnimation: function () {
      if (this._lottieAnim) {
        try {
          if (this._lottieAnim.pause) this._lottieAnim.pause()
          else if (this._lottieAnim.stop) this._lottieAnim.stop()
        } catch (_) {}
      }
      if (this._timer) { clearTimeout(this._timer); this._timer = null }
      if (this._contentTimer) { clearTimeout(this._contentTimer); this._contentTimer = null }
    },

    _resumeAnimation: function () {
      if (!this.data.visible) return
      if (this._lottieAnim) {
        try { if (this._lottieAnim.play) this._lottieAnim.play() } catch (_) {}
      }
      if (!this.data.showContent) {
        this._contentTimer = setTimeout(function () {
          if (this.data.visible) this.setData({ showContent: true })
        }.bind(this), 160)
      }
      this._timer = setTimeout(function () {
        this._hide(true)
      }.bind(this), this.data.duration)
    },

    _hide: function (emitDone) {
      this._clearTimers()
      this._destroyLottie()
      if (this.data.visible || this.data.showContent || this.data.mode !== 'hidden') {
        this.setData({ visible: false, showContent: false, mode: 'hidden', canvasReady: false, useLottie: false })
      }
      if (emitDone) this.triggerEvent('done')
    },

    _clearTimers: function () {
      if (this._timer) { clearTimeout(this._timer); this._timer = null }
      if (this._contentTimer) { clearTimeout(this._contentTimer); this._contentTimer = null }
      if (this._canvasTimer) { clearTimeout(this._canvasTimer); this._canvasTimer = null }
    },

    _destroyLottie: function () {
      if (this._lottieAnim) {
        try { this._lottieAnim.destroy() } catch (_) {}
        this._lottieAnim = null
      }
      this._canvas = null
      this._ctx = null
    },

    onTap: function () {
      this._hide(true)
    },
  },
})

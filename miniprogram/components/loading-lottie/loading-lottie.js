var LOTTIE_DATA_CACHE = null
var LOTTIE_MODULE_CACHE = undefined

function loadLottieData() {
  if (LOTTIE_DATA_CACHE !== null) return LOTTIE_DATA_CACHE

  var mod = null
  try { mod = require('../../assets/lottie/loading/loading.js') } catch (_) {}

  LOTTIE_DATA_CACHE = mod || false
  return LOTTIE_DATA_CACHE
}

function loadLottieModule() {
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
        SDKVersion: appBaseInfo.SDKVersion || '',
        platform: (deviceInfo.platform || '').toLowerCase(),
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

Component({
  properties: {
    text: { type: String, value: '' },
    size: { type: String, value: 'medium' },
    theme: { type: String, value: 'light' },
    enableLottie: { type: Boolean, value: true },
    loop: { type: Boolean, value: true },
    fallbackClass: { type: String, value: '' },
  },

  data: {
    mode: 'fallback',
    ready: false,
  },

  lifetimes: {
    attached: function () {
      this._canvas = null
      this._ctx = null
      this._lottieAnim = null
      this._pausedByPage = false
      this._detectSupport()
      this._start()
    },
    detached: function () {
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
      this._pausedByPage = true
      this._pauseAnimation()
    },
  },

  methods: {
    _detectSupport: function () {
      var info = getSystemInfo()
      var baseOk = compareVersion(info.SDKVersion, '2.9.0') >= 0
      var module = null
      var data = null

      if (this.data.enableLottie && baseOk && !isReducedMotionEnabled()) {
        try { module = loadLottieModule() } catch (_) { module = null }
        try { data = loadLottieData() } catch (_) { data = null }
      }

      this._lottieModule = module
      this._lottieData = data
      this._canUseLottie = !!(this.data.enableLottie && baseOk && module && data && !isReducedMotionEnabled())
    },

    _start: function () {
      if (!this._canUseLottie) {
        this._fallback()
        return
      }

      this.setData({ mode: 'lottie', ready: true }, function () {
        this._initCanvas()
      }.bind(this))
    },

    _initCanvas: function () {
      var self = this
      var query = this.createSelectorQuery()
      query.select('#loading-lottie-canvas')
        .fields({ node: true, size: true })
        .exec(function (res) {
          try {
            if (!res || !res[0] || !res[0].node) {
              self._fallback()
              return
            }
            var canvas = res[0].node
            var ctx = canvas.getContext && canvas.getContext('2d')
            if (!ctx) {
              self._fallback()
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
            self._startLottie()
          } catch (_) {
            self._fallback()
          }
        })
    },

    _startLottie: function () {
      if (!this._canUseLottie || !this._canvas || !this._ctx || !this._lottieData) {
        this._fallback()
        return
      }

      try {
        this._lottieAnim = this._lottieModule.loadAnimation({
          loop: this.data.loop,
          autoplay: true,
          animationData: this._lottieData,
          rendererSettings: {
            context: this._ctx,
            clearCanvas: true,
          },
          canvas: this._canvas,
        })
      } catch (_) {
        this._lottieAnim = null
        this._fallback()
      }
    },

    _fallback: function () {
      this._destroyLottie()
      if (this.data.mode !== 'fallback' || this.data.ready) {
        this.setData({ mode: 'fallback', ready: false })
      }
    },

    _pauseAnimation: function () {
      if (!this._lottieAnim) return
      try {
        if (this._lottieAnim.pause) this._lottieAnim.pause()
        else if (this._lottieAnim.stop) this._lottieAnim.stop()
      } catch (_) {}
    },

    _resumeAnimation: function () {
      if (!this._lottieAnim) return
      try { if (this._lottieAnim.play) this._lottieAnim.play() } catch (_) {}
    },

    _destroyLottie: function () {
      if (this._lottieAnim) {
        try { this._lottieAnim.destroy() } catch (_) {}
        this._lottieAnim = null
      }
      this._canvas = null
      this._ctx = null
    },
  },
})

var animationLoader = require('../../utils/animation-loader')

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
      this._alive = true
      this._canvas = null
      this._ctx = null
      this._lottieAnim = null
      this._pausedByPage = false
      this._detectSupport()
      this._start()
    },
    detached: function () {
      this._alive = false
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

      this._lottieModule = animationLoader.getLottieModule()
      this._lottieData = animationLoader.getLoadingData()
      this._canUseLottie = !!(this.data.enableLottie && baseOk && this._lottieModule && this._lottieData && !isReducedMotionEnabled())

      // 分包可能尚未就绪 — 触发加载并延迟重试一次
      if (!this._canUseLottie && this.data.enableLottie && baseOk && !isReducedMotionEnabled()) {
        var self = this
        animationLoader.loadAnimationPackage().then(function () {
          if (!self._alive) return
          self._lottieModule = animationLoader.getLottieModule()
          self._lottieData = animationLoader.getLoadingData()
          self._canUseLottie = !!(self._lottieModule && self._lottieData)
          if (self._canUseLottie && self.data.mode === 'fallback' && self.data.ready === false) {
            self._start()
          }
        })
      }
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
      query.select('.loading-lottie-canvas-wrap').fields({ size: true })
      query.select('#loading-lottie-canvas').fields({ node: true })
      query.exec(function (res) {
        try {
          if (!self._alive) return
          if (!res || !res[1] || !res[1].node) {
            self._fallback()
            return
          }
          var wrapSize = res[0] || {}
          var canvasNode = res[1].node
          var ctx = canvasNode.getContext && canvasNode.getContext('2d')
          if (!ctx) {
            self._fallback()
            return
          }

          var cssW = wrapSize.width || 240
          var cssH = wrapSize.height || 180
          var windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
          var dpr = windowInfo.pixelRatio || 1

          canvasNode.width = Math.round(cssW * dpr)
          canvasNode.height = Math.round(cssH * dpr)

          self._canvas = canvasNode
          self._ctx = ctx
          self._lottieModule.setup(canvasNode)
          self._startLottie()
        } catch (_) {
          if (self._alive) self._fallback()
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

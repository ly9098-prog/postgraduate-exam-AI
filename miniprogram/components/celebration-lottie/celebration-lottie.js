// 庆祝动效组件 —— Lottie 优先 → Canvas 粒子 → CSS 降级（三级保障）
// 使用方式:
//   <celebration-lottie show="{{showCelebration}}"
//     type="excellent"  // excellent | steady | final | combo | group | focus
//     title="高质量挑战完成"
//     detail="答对 5/5 题 · 正确率 100%"
//     motto="继续保持，薄弱点会越来越少"
//     reward-text="专注星光 +5"
//     duration="{{2800}}"
//     bind:done="onCelebrationDone" />
//
// Lottie 动画文件位于 /assets/lottie/ ，需先执行 微信开发者工具 → 构建 npm

// ── 类型 → Lottie JSON 映射 ──
var LOTTIE_MAP
try {
  LOTTIE_MAP = {
    excellent: require('../../assets/lottie/trophy.json'),
    practice: require('../../assets/lottie/success-check.json'),
    steady: require('../../assets/lottie/success-check.json'),
    final: require('../../assets/lottie/celebration.json'),
    combo: require('../../assets/lottie/fireworks.json'),
    group: require('../../assets/lottie/medal.json'),
    focus: require('../../assets/lottie/study.json'),
  }
} catch (_) { LOTTIE_MAP = null }

// ── 尝试加载 lottie-miniprogram ──
var lottieModule = null
try {
  lottieModule = require('lottie-miniprogram')
} catch (_) {
  // 如果 build npm 之前不可用，尝试直接路径
  try {
    lottieModule = require('../../miniprogram_npm/lottie-miniprogram/index')
  } catch (_2) { lottieModule = null }
}

// ── 调色板（Canvas / CSS 降级使用）──
var TYPE_PALETTE = {
  practice:   { primary: '#4F7FFF', secondary: '#22C55E', accent: '#FFD700', icon: '✓' },
  excellent:  { primary: '#22C55E', secondary: '#7BD88F', accent: '#FFFFFF', icon: '✓' },
  steady:     { primary: '#4F7FFF', secondary: '#6EC1FF', accent: '#FFFFFF', icon: '✓' },
  final:      { primary: '#22C55E', secondary: '#A8E6A1', accent: '#FFD700', icon: '★' },
  combo:      { primary: '#F59E0B', secondary: '#FF6B35', accent: '#FFD166', icon: '🔥' },
  group:      { primary: '#6EC1FF', secondary: '#4F7FFF', accent: '#FFFFFF', icon: '✓' },
  focus:      { primary: '#8B5CF6', secondary: '#A78BFA', accent: '#FFFFFF', icon: '!' },
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
      this._particles = []
      this._rafId = null
      this._startTime = 0
      this._lottieAnim = null
      this._reducedMotion = false
      // 判断能否走 Lottie 渲染
      this._canLottie = !!(lottieModule && LOTTIE_MAP && LOTTIE_MAP[this.data.type || 'steady'])
      // 检测 reduced-motion 偏好
      try {
        var sysInfo = wx.getSystemInfoSync()
        if (sysInfo && sysInfo.reduceMotion === true) {
          this._reducedMotion = true
        }
      } catch (_) {}
    },
    ready: function () {
      this._initCanvas()
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
          self._cw = width
          self._ch = height

          // 尝试初始化 Lottie
          if (self._canLottie && lottieModule) {
            try {
              lottieModule.setup(canvas)
              self.setData({ canvasReady: true, useLottie: true })
              return
            } catch (_) {}
          }

          // 回退到 Canvas 2D 粒子动画
          self.setData({ canvasReady: true, useLottie: false })
        })
    },

    _startAnimation: function () {
      if (this._reducedMotion) return
      if (this.data.useLottie && this._canLottie) {
        this._startLottie()
      } else {
        this._startCanvasParticles()
      }
    },

    /* ──── Lottie 渲染路径 ──── */

    _startLottie: function () {
      var self = this
      var animationData = LOTTIE_MAP && LOTTIE_MAP[this.data.type]
      if (!animationData || !lottieModule) {
        this._startCanvasParticles()
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
        // 绘制暗色背景（Lottie 动画本身不含全屏背景）
        this._drawLottieBg()
      } catch (e) {
        console.error('[celebration-lottie] Lottie 加载失败，降级到 Canvas 粒子', e)
        this._lottieAnim = null
        this.setData({ useLottie: false })
        this._startCanvasParticles()
      }
    },

    _drawLottieBg: function () {
      if (!this._ctx || !this._cw || !this._ch) return
      this._ctx.fillStyle = 'rgba(11, 17, 33, 0.72)'
      this._ctx.fillRect(0, 0, this._cw, this._ch)
    },

    /* ──── Canvas 2D 粒子渲染路径（降级）─── */

    _startCanvasParticles: function () {
      var palette = TYPE_PALETTE[this.data.type] || TYPE_PALETTE.steady
      this._palette = palette
      this._startTime = Date.now()
      this._bgAlpha = 0
      this._spawnParticles()
      this._renderLoop()
    },

    _stopAnimation: function () {
      if (this._rafId) {
        if (this._canvas && this._canvas.cancelAnimationFrame) {
          this._canvas.cancelAnimationFrame(this._rafId)
        } else {
          cancelAnimationFrame(this._rafId)
        }
        this._rafId = null
      }
      this._particles = []
    },

    _spawnParticles: function () {
      var p = this._palette
      var cx = this._cw / 2
      var cy = this._ch / 2
      var colors = [p.primary, p.secondary, p.accent, p.primary, p.secondary]
      for (var i = 0; i < 28; i++) {
        var angle = (Math.PI * 2 * i) / 28 + (Math.random() - 0.5) * 0.4
        var speed = 1.8 + Math.random() * 4.2
        var size = 3 + Math.random() * 7
        this._particles.push({
          x: cx, y: cy,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          size: size, alpha: 1,
          color: colors[Math.floor(Math.random() * colors.length)],
          delay: Math.floor(Math.random() * 120),
        })
      }
      for (var j = 0; j < 10; j++) {
        this._particles.push({
          x: cx + (Math.random() - 0.5) * 30,
          y: cy + (Math.random() - 0.5) * 30,
          vx: (Math.random() - 0.5) * 7,
          vy: (Math.random() - 0.5) * 7 - 2,
          size: 2 + Math.random() * 4,
          alpha: 1,
          color: p.accent,
          delay: 80 + Math.floor(Math.random() * 100),
          sparkle: true,
        })
      }
    },

    _renderLoop: function () {
      if (!this._ctx || !this._cw || !this._ch) return
      var ctx = this._ctx
      var w = this._cw
      var h = this._ch
      var cx = w / 2
      var cy = h / 2
      var elapsed = Date.now() - this._startTime
      var p = this._palette

      ctx.clearRect(0, 0, w, h)

      this._bgAlpha = Math.min(0.72, this._bgAlpha + 0.04)
      ctx.fillStyle = 'rgba(11, 17, 33, ' + this._bgAlpha + ')'
      ctx.fillRect(0, 0, w, h)

      for (var i = this._particles.length - 1; i >= 0; i--) {
        var pt = this._particles[i]
        if (elapsed < pt.delay) continue
        var life = (elapsed - pt.delay) / 1000
        pt.x += pt.vx
        pt.y += pt.vy
        pt.vy += 0.06
        pt.alpha = Math.max(0, 1 - life / 1.5)
        if (pt.alpha <= 0) {
          this._particles.splice(i, 1)
          continue
        }
        ctx.globalAlpha = pt.alpha
        ctx.fillStyle = pt.color
        if (pt.sparkle) {
          this._drawStar(ctx, pt.x, pt.y, pt.size)
        } else {
          ctx.beginPath()
          ctx.arc(pt.x, pt.y, pt.size, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      ctx.globalAlpha = 1

      var t = Math.min(1, elapsed / 400)
      var eased = 1 - Math.pow(1 - t, 3)
      var badgeR = 50 * eased
      ctx.save()
      ctx.translate(cx, cy * 0.65)
      ctx.scale(eased, eased)

      var glow = ctx.createRadialGradient(0, 0, badgeR * 0.5, 0, 0, badgeR * 1.6)
      glow.addColorStop(0, p.primary + '40')
      glow.addColorStop(1, 'transparent')
      ctx.fillStyle = glow
      ctx.beginPath()
      ctx.arc(0, 0, badgeR * 1.6, 0, Math.PI * 2)
      ctx.fill()

      var grad = ctx.createLinearGradient(-badgeR, -badgeR, badgeR, badgeR)
      grad.addColorStop(0, p.primary)
      grad.addColorStop(1, p.secondary)
      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.arc(0, 0, badgeR, 0, Math.PI * 2)
      ctx.fill()

      ctx.fillStyle = '#FFFFFF'
      ctx.font = 'bold ' + (badgeR * 0.9) + 'px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(p.icon, 0, badgeR * 0.06)
      ctx.restore()

      if (elapsed < this.data.duration - 100) {
        var raf = this._canvas && this._canvas.requestAnimationFrame
          ? this._canvas.requestAnimationFrame(this._renderLoop.bind(this))
          : requestAnimationFrame(this._renderLoop.bind(this))
        this._rafId = raf
      }
    },

    _drawStar: function (ctx, x, y, size) {
      var spikes = 5
      var outerR = size
      var innerR = size * 0.4
      ctx.beginPath()
      for (var i = 0; i < spikes * 2; i++) {
        var r = i % 2 === 0 ? outerR : innerR
        var angle = (Math.PI * 2 * i) / (spikes * 2) - Math.PI / 2
        var sx = x + Math.cos(angle) * r
        var sy = y + Math.sin(angle) * r
        if (i === 0) ctx.moveTo(sx, sy)
        else ctx.lineTo(sx, sy)
      }
      ctx.closePath()
      ctx.fill()
    },

    onTap: function () {
      if (this._timer) clearTimeout(this._timer)
      if (this._contentTimer) clearTimeout(this._contentTimer)
      this._stopAnimation()
      if (this._lottieAnim) {
        try { this._lottieAnim.destroy() } catch (_) {}
        this._lottieAnim = null
      }
      this.setData({ visible: false, showContent: false })
      this.triggerEvent('done')
    },
  },
})

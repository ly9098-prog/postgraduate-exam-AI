// 庆祝动效组件 —— Lottie 优先 + CSS 降级
// 使用方式:
//   <celebration-lottie show="{{showCelebration}}"
//     type="excellent"  // excellent | steady | final | combo
//     duration="{{2800}}"
//     bind:done="onCelebrationDone" />
//
// 需要先执行: npm install && 微信开发者工具 → 工具 → 构建 npm
Component({
  properties: {
    show: { type: Boolean, value: false },
    type: { type: String, value: 'steady' },
    duration: { type: Number, value: 2800 },
  },

  data: {
    lottieReady: false,
    fallbackMode: true,
    visible: false,
  },

  observers: {
    show(val) {
      if (val) {
        this.setData({ visible: true })
        if (this._timer) clearTimeout(this._timer)
        this._timer = setTimeout(() => {
          this.setData({ visible: false })
          this.triggerEvent('done')
        }, this.data.duration)
      }
    },
  },

  lifetimes: {
    attached() {
      // 检测 lottie-miniprogram 是否可用
      try {
        // eslint-disable-next-line
        const lottie = require('lottie-miniprogram')
        if (lottie) {
          this.setData({ lottieReady: true, fallbackMode: false })
        }
      } catch (_) {
        this.setData({ fallbackMode: true })
      }
    },
    detached() {
      if (this._timer) clearTimeout(this._timer)
    },
  },

  methods: {
    onTap() {
      if (this._timer) clearTimeout(this._timer)
      this.setData({ visible: false })
      this.triggerEvent('done')
    },
  },
})

Component({
  properties: {
    enabled: { type: Boolean, value: true },
    delegate: { type: Boolean, value: false },
  },

  data: { visible: false },

  observers: {
    enabled(enabled) {
      if (enabled) this._handling = false
      this._syncGuard()
    },
    delegate() {
      this._syncGuard()
    },
  },

  lifetimes: {
    attached() {
      this._alive = true
      this._active = true
      this._syncGuard()
    },
    detached() {
      this._alive = false
    },
  },

  pageLifetimes: {
    show() {
      this._active = true
      this._handling = false
      this._syncGuard()
    },
    hide() {
      this._active = false
      this._syncGuard()
    },
  },

  methods: {
    _syncGuard() {
      const pages = getCurrentPages()
      // Delegated guards hand the back gesture to the page, so they must also
      // protect pushed pages; the root-only default keeps _returnHome safe.
      const inScope = pages.length > 0 &&
        (this.properties.delegate || pages.length === 1)
      const visible = !!(this._alive && this._active && !this._handling &&
        this.properties.enabled && inScope)
      if (this._alive && this.data.visible !== visible) this.setData({ visible })
    },

    onAfterLeave() {
      if (!this._alive || !this._active || !this.properties.enabled ||
        !this.data.visible || this._handling) return
      this._handling = true
      this.setData({ visible: false }, () => {
        if (!this._alive || !this._active) return
        if (this.properties.delegate) {
          this.triggerEvent('back')
          wx.nextTick(() => {
            this._handling = false
            this._syncGuard()
          })
        } else this._returnHome()
      })
    },

    _returnHome() {
      wx.reLaunch({
        url: '/pages/home/home',
        fail: () => {
          if (!this._alive || !this._active) return
          this._handling = false
          wx.showToast({ title: '返回失败，请再试一次', icon: 'none' })
          this._syncGuard()
        },
      })
    },
  },
})

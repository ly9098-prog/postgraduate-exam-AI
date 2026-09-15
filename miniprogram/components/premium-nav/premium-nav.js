Component({
  properties: {
    title: { type: String, value: '' },
    caption: { type: String, value: '' },
    variant: { type: String, value: 'light' },
    showBack: { type: Boolean, value: true },
    fixed: { type: Boolean, value: true },
  },

  data: {
    navHeight: 88,
    statusBarHeight: 20,
    contentHeight: 44,
    menuRight: 16,
    menuWidth: 88,
  },

  lifetimes: {
    attached() {
      this._measureNavigation()
    },
  },

  methods: {
    _measureNavigation() {
      let statusBarHeight = 20
      let windowWidth = 375
      try {
        const info = wx.getWindowInfo ? wx.getWindowInfo() : {}
        statusBarHeight = Number(info.statusBarHeight || 20)
        windowWidth = Number(info.windowWidth || info.screenWidth || 375)
      } catch (_) {}

      let menu = null
      try {
        menu = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect()
      } catch (_) {}

      const menuTop = menu && menu.top ? Number(menu.top) : statusBarHeight + 6
      const menuHeight = menu && menu.height ? Number(menu.height) : 32
      const menuRight = menu && menu.right ? Math.max(12, windowWidth - Number(menu.right)) : 12
      const menuWidth = menu && menu.width ? Number(menu.width) : 88
      const verticalGap = Math.max(4, menuTop - statusBarHeight)
      const contentHeight = menuHeight + verticalGap * 2
      const navHeight = statusBarHeight + contentHeight

      this.setData({
        navHeight,
        statusBarHeight,
        contentHeight,
        menuRight,
        menuWidth,
      })
    },

    onBack() {
      this.triggerEvent('back')
    },
  },
})

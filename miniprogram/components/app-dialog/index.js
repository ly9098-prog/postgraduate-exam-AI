/**
 * app-dialog — shared custom prompt / choice surface.
 * Reuses the app's existing submit-confirm visual language instead of native
 * platform modal/action-sheet UI.
 */
Component({
  properties: { theme: { type: String, value: 'default' } },
  data: {
    visible: false,
    mode: 'confirm',
    scenario: 'all-done',
    title: '',
    message: '',
    confirmText: '确定',
    cancelText: '取消',
    eyebrow: '',
    hideCancel: false,
    hideEyebrow: false,
    hideIcon: false,
    hideAccent: false,
    maskClose: false,
    items: [],
    layout: 'default',
    subtitle: '',
    metaItems: [],
    iconImage: '',
  },
  methods: {
    show(opts = {}) {
      if (this._confirmResolve) return Promise.resolve(false)
      this._dialogMode = 'confirm'
      this.setData({
        visible: true,
        mode: 'confirm',
        scenario: opts.scenario || 'all-done',
        title: opts.title || '',
        message: opts.message || '',
        confirmText: opts.confirmText || '确定',
        cancelText: opts.cancelText || '取消',
        eyebrow: opts.eyebrow || '',
        hideCancel: opts.showCancel === false || !!opts.hideCancel,
        hideEyebrow: !!opts.hideEyebrow,
        hideIcon: !!opts.hideIcon,
        hideAccent: !!opts.hideAccent,
        maskClose: !!opts.maskClose,
        items: [],
        layout: opts.layout || 'default',
        subtitle: opts.subtitle || '',
        metaItems: (Array.isArray(opts.metaItems) ? opts.metaItems : []).map((item) => ({
          icon: item && item.icon ? String(item.icon) : 'dot',
          text: item && item.text != null ? String(item.text) : '',
        })).filter((item) => item.text).slice(0, 3),
        iconImage: opts.iconImage || '',
      })
      return new Promise((resolve) => { this._confirmResolve = resolve })
    },

    showOptions(opts = {}) {
      if (this._confirmResolve) return Promise.resolve(-1)
      const dangerIndexes = new Set(Array.isArray(opts.dangerIndexes) ? opts.dangerIndexes.map(Number) : [])
      const items = (Array.isArray(opts.items) ? opts.items : []).map((item, index) => ({
        index,
        label: String(item && typeof item === 'object' ? (item.label || item.name || '') : item || ''),
        danger: dangerIndexes.has(index) || !!(item && typeof item === 'object' && item.danger),
      })).filter(item => item.label)
      if (!items.length) return Promise.resolve(-1)
      this._dialogMode = 'options'
      this.setData({
        visible: true,
        mode: 'options',
        scenario: opts.scenario || 'info',
        title: opts.title || '请选择',
        message: opts.message || '',
        cancelText: opts.cancelText || '取消',
        hideCancel: false,
        hideEyebrow: true,
        hideIcon: !!opts.hideIcon,
        hideAccent: !!opts.hideAccent,
        maskClose: opts.maskClose !== false,
        items,
        layout: 'default',
        subtitle: '',
        metaItems: [],
        iconImage: '',
      })
      return new Promise((resolve) => { this._confirmResolve = resolve })
    },

    _close(result) {
      if (!this._confirmResolve) return
      this.setData({ visible: false })
      const resolve = this._confirmResolve
      this._confirmResolve = null
      this._dialogMode = ''
      resolve(result)
    },

    noop() {},
    onMaskTap() { if (this.data.maskClose) this._close(this._dialogMode === 'options' ? -1 : false) },
    onConfirm() { this._close(true) },
    onCancel() { this._close(this._dialogMode === 'options' ? -1 : false) },
    onOption(e) {
      const index = Number(e.currentTarget.dataset.index)
      this._close(Number.isFinite(index) ? index : -1)
    },
  },
})

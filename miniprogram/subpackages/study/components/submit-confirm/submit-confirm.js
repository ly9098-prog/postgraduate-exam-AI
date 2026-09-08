/**
 * submit-confirm — Custom confirmation modal
 * Replaces wx.showModal for submit confirmation.
 * Usage:
 *   const confirmed = await this.selectComponent('#submitConfirm').show({
 *     scenario: 'unanswered',    // 'all-done' | 'unanswered'
 *     title: '还有题目未作答',
 *     message: '还有 3 道题未作答，确定提交吗？',
 *     confirmText: '确定提交',
 *     cancelText: '继续作答',
 *   })
 *   if (!confirmed) return
 */
Component({
  data: {
    visible: false,
    scenario: 'all-done',
    title: '',
    message: '',
    confirmText: '确定提交',
    cancelText: '取消',
    eyebrow: '',
    hideCancel: false,
    hideEyebrow: false,
  },
  methods: {
    show(opts) {
      if (this._confirmResolve) return Promise.resolve(false)
      this.setData({
        visible: true,
        scenario: opts.scenario || 'all-done',
        title: opts.title || '',
        message: opts.message || '',
        confirmText: opts.confirmText || '确定提交',
        cancelText: opts.cancelText || '取消',
        eyebrow: opts.eyebrow || '',
        hideCancel: opts.showCancel === false || !!opts.hideCancel,
        hideEyebrow: !!opts.hideEyebrow,
      })
      return new Promise(function (resolve) {
        this._confirmResolve = resolve
      }.bind(this))
    },

    _close(result) {
      if (!this._confirmResolve) return
      this.setData({ visible: false })
      var resolve = this._confirmResolve
      this._confirmResolve = null
      resolve(result)
    },

    noop() {},
    onConfirm() { this._close(true) },
    onCancel() { this._close(false) },
  },
})

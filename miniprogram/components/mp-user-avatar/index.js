const canReviewNickname = (() => {
  try {
    return !!(wx.canIUse && wx.canIUse('input.bindnicknamereview'))
  } catch (_) {
    return false
  }
})()

Component({
  options: {
    addGlobalClass: true,
  },

  externalClasses: ['avatar-class', 'nickname-class'],

  properties: {
    avatar: { type: String, value: '' },
    nickname: { type: String, value: '' },
    defaultAvatar: { type: String, value: '' },
    defaultNickname: { type: String, value: '' },
    editable: { type: Boolean, value: true },
    isDevtools: { type: Boolean, value: false },
  },

  data: {
    currentAvatar: '',
    currentNickname: '',
  },

  lifetimes: {
    attached() {
      this._pendingNickname = ''
      this._syncFromProps()
    },
  },

  observers: {
    'avatar,nickname': function onProfilePropsChanged() {
      this._syncFromProps()
    },
  },

  methods: {
    _syncFromProps() {
      const avatar = String(this.properties.avatar || '')
      const nickname = String(this.properties.nickname || '')
      const patch = {}
      if (avatar !== this.data.currentAvatar) patch.currentAvatar = avatar
      if (nickname !== this.data.currentNickname) patch.currentNickname = nickname
      if (Object.keys(patch).length) this.setData(patch)
    },

    _isCancel(error) {
      const message = String((error && (error.errMsg || error.message)) || '')
      return /cancel/i.test(message)
    },

    _emitChange(field) {
      this.triggerEvent('change', {
        field,
        userInfo: {
          avatar: this.data.currentAvatar || '',
          nickname: String(this.data.currentNickname || '').trim(),
        },
      })
    },

    _applyAvatar(avatarUrl) {
      if (!avatarUrl) return
      this.setData({ currentAvatar: avatarUrl }, () => {
        this._emitChange('avatar')
      })
    },

    onChooseAvatar(event) {
      if (!this.properties.editable) return
      const avatarUrl = event && event.detail && event.detail.avatarUrl
      if (avatarUrl) this._applyAvatar(avatarUrl)
    },

    async chooseAvatarInDevtools() {
      if (!this.properties.editable) return
      try {
        const result = await wx.chooseMedia({
          count: 1,
          mediaType: ['image'],
          sourceType: ['album'],
          sizeType: ['compressed'],
        })
        const file = result && Array.isArray(result.tempFiles) ? result.tempFiles[0] : null
        const avatarUrl = file && (file.tempFilePath || file.path)
        if (avatarUrl) this._applyAvatar(avatarUrl)
      } catch (error) {
        if (this._isCancel(error)) return
        this.triggerEvent('error', {
          code: 'AVATAR_PICK_FAILED',
          message: '头像选择失败，请重试',
        })
      }
    },

    onNicknameInput(event) {
      if (!this.properties.editable) return
      const value = String((event && event.detail && event.detail.value) || '')
      this.setData({ currentNickname: value })
    },

    onNicknameBlur(event) {
      if (!this.properties.editable) return
      const value = String((event && event.detail && event.detail.value) || this.data.currentNickname || '').trim()
      this.setData({ currentNickname: value })
      if (canReviewNickname && !this.properties.isDevtools) {
        this._pendingNickname = value
        return
      }
      this._emitChange('nickname')
    },

    onNicknameReview(event) {
      if (!this.properties.editable || this.properties.isDevtools) return
      const pass = !!(event && event.detail && event.detail.pass)
      if (!pass) {
        this.triggerEvent('error', {
          code: 'NICKNAME_REVIEW_REJECTED',
          message: '该昵称暂不可使用，请换一个昵称',
        })
        return
      }
      const value = String(
        (event && event.detail && event.detail.nickname) ||
        this._pendingNickname ||
        this.data.currentNickname || ''
      ).trim()
      this._pendingNickname = ''
      this.setData({ currentNickname: value })
      this._emitChange('nickname')
    },
  },
})

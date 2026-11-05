const auth = require('../../utils/auth')
const {
  GOAL_OPTIONS,
  TODAY_GOAL_TOTAL,
  growthPageMethods,
} = require('./utils/growth-page-controller')
const { homeCanvasMethods } = require('./utils/home-canvas')
Page({
  ...growthPageMethods,
  ...homeCanvasMethods,
  _growthApi: null,

  data: {
    guestMode: true,
    user: {},
    displayName: '研友',
    userInitial: '研',
    showProfileSheet: false,
    profileNickname: '',
    profileAvatarPreview: '',
    profileAvatarPath: '',
    profileSaving: false,
    profileSaveState: '',
    isDevtools: false,
    greeting: '',
    dateStr: '',
    motto: '',

    navHeight: 88,
    statusBarHeight: 20,
    navContentHeight: 44,
    navRightPadding: 116,

    _animStreakDays: 0,
    studyLevel: 'Lv1 起步',
    levelProgress: 0,
    _animLevelProgress: 0,
    _animGoalDone: 0,
    todayGoalTotal: TODAY_GOAL_TOTAL,
    goalOptions: GOAL_OPTIONS,
    showGoalPicker: false,

    dueReviewCount: 0,
    remainingCount: TODAY_GOAL_TOTAL,
    primaryTaskType: 'practice',
    primaryTaskKicker: 'TODAY PLAN · 优先级 01',
    primaryTaskTitle: `完成今日 ${TODAY_GOAL_TOTAL} 道练习`,
    primaryTaskDesc: '先完成一组练习建立节奏，之后再根据结果安排复习。',
    primaryTaskAction: '开始练习',
    secondaryTaskAction: '查看复习计划',
    studyHubAvailable: false,
    studyHubFallback: false,
    hubPrimaryTask: null,
    hubSecondaryTask: null,
    hubTasks: [],
    hubRecommendationCount: 0,
    hubCompletedRecommendationCount: 0,
    subjectMastery: [],
    studyPlanConfigured: false,
    planDaysRemaining: 0,
    planPhaseLabel: '',
    planTargetDateText: '',
    planTodayText: '尚未设置长期计划',
    planWeeklyText: '',
    planProgressPercent: 0,
    planPrimaryText: '设置目标日期后生成每日配比',

    expText: '0 / 50 EXP',
    nextLevelText: '距离 Lv2 还差 50 题',
    dailyBoostText: '完成今日目标后，可点亮坚持徽章',
    badgeList: [],
    badgeTitle: '今日待点亮',
    missionText: '完成一组练习，点亮今日目标',
  },

  /* 实例状态 — 不通过 setData 写入 */
  _authed: false,
  _alive: false,
  _visible: false,
  _showSeq: 0,
  _growthSeq: 0,
  _profileSaveSeq: 0,
  _hasGrowthSnapshot: false,
  _growthTargets: { streakDays: 0, todayGoalDone: 0, levelProgress: 0 },
  _lastDashboardSubjectStats: [],
  _animTimer: null,
  _profileAutoSaveTimer: null,
  _profileSavedHintTimer: null,
  _profileDraftVersion: 0,
  _profileNicknameDraftRaw: '',
  _examRoutePending: false,
  _resumeAttempted: false,

  onLoad() {
    this._alive = true
    this.setData({ guestMode: !auth.isLoggedIn() })
    this.measureNavigation()
    this.detectRuntime()
  },

  async onShow() {
    this._alive = true
    this._visible = true
    this._examRoutePending = false
    // chooseAvatar 会打开微信原生选择界面，返回页面时会再次触发 onShow。
    // 资料弹层打开期间绝不做 setData / 用户同步，避免在原生开放能力完成回调前
    // 重建 button/input 节点，导致头像回调丢失或 nickname 快捷填入条被卸载。
    if (this.data.showProfileSheet) return
    const showSeq = ++this._showSeq
    await this._validateHomeSession()
    if (!this._alive || !this._visible || showSeq !== this._showSeq) return
    this._isAdmin = this._authed ? auth.isAdmin() : false
    this._applyHomeBasePatch()
    if (this._authed) this._maybeResumeColdLaunch()
    if (!this._authed) return
    const canContinue = await this._syncHomeUser(showSeq)
    if (!canContinue) return
    // 个人资料仅在用户主动点击首页头像入口时打开，不在首页自动弹出。
    await this.loadGrowthSnapshot(showSeq)
  },

  _applyHomeBasePatch() {
    const localUser = this._authed ? (auth.getUser() || {}) : {}
    const basePatch = {
      user: localUser,
      displayName: this.getDisplayName(localUser),
      userInitial: this.getUserInitial(localUser),
      greeting: this.getGreeting(),
      dateStr: this.getDateStr(),
      motto: this.getMotto(),
    }
    if (!this._authed || !this._hasGrowthSnapshot) {
      Object.assign(basePatch, {
        _animStreakDays: 0,
        _animGoalDone: 0,
        _animLevelProgress: 0,
        ...this.getGrowthFallback(),
      })
    }
    if (!this._authed) Object.assign(basePatch, this._guestBasePatch())
    else basePatch.guestMode = false
    this.setData(basePatch)
  },

  async _syncHomeUser(showSeq) {
    try {
      const syncedUser = await auth.syncCurrentUser()
      if (!this._alive || !this._visible || showSeq !== this._showSeq) return false
      if (syncedUser) {
        this._isAdmin = auth.isAdmin()
        this.setData({
          user: syncedUser,
          displayName: this.getDisplayName(syncedUser),
          userInitial: this.getUserInitial(syncedUser),
        })
      }
      return true
    } catch (e) {
      // Profile/permission sync is helpful but must not block the home dashboard.
      // A transient /users/me failure should still allow growth data to load.
      console.error('同步用户权限失败', e)
      if (!this._alive || !this._visible || showSeq !== this._showSeq) return false
      this._authed = auth.isLoggedIn()
      if (!this._authed) this._applyHomeBasePatch()
      return this._authed
    }
  },

  _getProfileNickname(user) {
    const profile = user || {}
    const value = profile.nickname || profile.nickName || profile.name || ''
    return this._normalizeProfileNickname(value)
  },

  _getProfileAvatar(user) {
    const profile = user || {}
    return String(profile.avatar_url || profile.avatarUrl || profile.avatar || '').trim()
  },

  _isProfileSetupComplete(user) {
    return !!this._getProfileNickname(user) && !!this._getProfileAvatar(user)
  },

  async openProfileSheet() {
    if (!this._authed) {
      this.openLoginFromHome()
      return
    }

    // 头像和 nickname input 都属于微信隐私能力。项目自己的协议勾选只记录
    // 业务侧同意状态，并不会自动完成微信宿主侧的隐私授权。尤其是
    // input[type=nickname] 本身不会可靠触发隐私授权弹窗，因此必须在
    // 用户主动进入资料设置时先完成一次宿主授权预检。
    const privacyReady = await this._ensureWechatProfilePrivacyAuthorized()
    if (!privacyReady || !this._alive) return

    const currentUser = this.data.user || {}
    const user = Object.keys(currentUser).length ? currentUser : (auth.getUser() || {})
    clearTimeout(this._profileAutoSaveTimer)
    clearTimeout(this._profileSavedHintTimer)
    this._profileAutoSaveTimer = null
    this._profileSavedHintTimer = null
    this._profileNicknameDraftRaw = ''
    this.setData({
      showProfileSheet: true,
      profileNickname: this._getProfileNickname(user),
      profileAvatarPreview: this._getProfileAvatar(user),
      profileAvatarPath: '',
      profileSaveState: '',
    })
  },

  _ensureWechatProfilePrivacyAuthorized() {
    if (this.data.isDevtools || typeof wx.requirePrivacyAuthorize !== 'function') {
      return Promise.resolve(true)
    }
    return new Promise((resolve) => {
      let settled = false
      const finish = (value) => {
        if (settled) return
        settled = true
        resolve(!!value)
      }
      const requireAuthorization = () => this._requireWechatPrivacyAuthorization(finish)
      this._checkWechatPrivacySetting(requireAuthorization, finish)
    })
  },

  _requireWechatPrivacyAuthorization(finish) {
    try {
      wx.requirePrivacyAuthorize({
        success: () => finish(true),
        fail: (error) => this._handleWechatPrivacyFailure(error, finish),
      })
    } catch (error) {
      console.warn('[PROFILE_PRIVACY] requirePrivacyAuthorize unavailable', error)
      finish(true)
    }
  },

  _handleWechatPrivacyFailure(error, finish) {
    const message = String((error && (error.errMsg || error.message)) || '')
    if (!/cancel|deny|refuse|disagree/i.test(message)) {
      console.warn('[PROFILE_PRIVACY] requirePrivacyAuthorize failed', error)
    }
    wx.showToast({
      title: /scope is not declared|privacy agreement/i.test(message)
        ? '请先在小程序隐私保护指引中声明头像昵称用途'
        : '同意隐私保护指引后才能设置头像昵称',
      icon: 'none',
      duration: 2600,
    })
    finish(false)
  },

  _checkWechatPrivacySetting(requireAuthorization, finish) {
    if (typeof wx.getPrivacySetting !== 'function') {
      requireAuthorization()
      return
    }
    try {
      wx.getPrivacySetting({
        success: (result) => {
          if (result && result.needAuthorization) requireAuthorization()
          else finish(true)
        },
        fail: () => requireAuthorization(),
      })
    } catch (_) {
      requireAuthorization()
    }
  },

  closeProfileSheet() {
    if (this.data.profileSaving) return
    clearTimeout(this._profileAutoSaveTimer)
    clearTimeout(this._profileSavedHintTimer)
    this._profileAutoSaveTimer = null
    this._profileSavedHintTimer = null
    try { wx.hideKeyboard && wx.hideKeyboard() } catch (_) {}
    this.setData({
      showProfileSheet: false,
      profileAvatarPath: '',
      profileSaveState: '',
    })
  },

  noop() {},

  detectRuntime() {
    let platform = ''
    try {
      const info = wx.getDeviceInfo ? (wx.getDeviceInfo() || {}) : {}
      platform = String(info.platform || '').toLowerCase()
    } catch (_) {}
    this.setData({ isDevtools: platform === 'devtools' })
  },

  _isNativeCancel(error) {
    const message = String((error && (error.errMsg || error.message)) || '')
    return /cancel/i.test(message)
  },

  _normalizeProfileNickname(value) {
    return String(value || '').trim().replace(/\s+/g, ' ')
  },

  _scheduleProfileSaveIfReady(field = '') {
    if (this.data.profileSaving || !this._alive || !this.data.showProfileSheet) return
    const nickname = this._normalizeProfileNickname(this.data.profileNickname)
    const currentNickname = this._getProfileNickname(this.data.user)
    const storedAvatar = this._getProfileAvatar(this.data.user)
    const hasAvatar = !!(this.data.profileAvatarPath || this.data.profileAvatarPreview || storedAvatar)
    const nicknameChanged = nickname !== currentNickname
    const avatarChanged = !!this.data.profileAvatarPath

    if (!nickname || !hasAvatar) {
      if (this.data.profileSaveState !== 'editing') this.setData({ profileSaveState: '' })
      return
    }
    // 已有完整资料时，只有真正发生字段变化才提交。避免点击已有昵称后
    // native nickname picker 触发 blur，导致用旧值自动保存并关闭/打断编辑。
    if (field === 'nickname' && !nicknameChanged) {
      this.setData({ profileSaveState: '' })
      return
    }
    if (field === 'avatar' && !avatarChanged) return
    if (!nicknameChanged && !avatarChanged) return

    clearTimeout(this._profileAutoSaveTimer)
    this.setData({ profileSaveState: 'pending' })
    this._profileAutoSaveTimer = setTimeout(() => {
      this._profileAutoSaveTimer = null
      if (this._alive && this.data.showProfileSheet) this.saveProfile()
    }, 260)
  },

  _applyProfileAvatar(avatarPath) {
    if (!avatarPath) return
    clearTimeout(this._profileSavedHintTimer)
    this._profileSavedHintTimer = null
    this._profileDraftVersion++
    this.setData({
      profileAvatarPreview: avatarPath,
      profileAvatarPath: avatarPath,
      profileSaveState: 'pending',
    }, () => this._scheduleProfileSaveIfReady('avatar'))
  },

  _chooseMediaFromAlbum() {
    return new Promise((resolve, reject) => {
      if (typeof wx.chooseMedia !== 'function') {
        reject(new Error('wx.chooseMedia unavailable'))
        return
      }
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album'],
        sizeType: ['compressed'],
        success: (res) => {
          const file = res && Array.isArray(res.tempFiles) ? res.tempFiles[0] : null
          const path = file && (file.tempFilePath || file.path)
          path ? resolve(path) : reject(new Error('chooseMedia returned no image path'))
        },
        fail: reject,
      })
    })
  },

  _chooseImageFromAlbum() {
    return new Promise((resolve, reject) => {
      if (typeof wx.chooseImage !== 'function') {
        reject(new Error('wx.chooseImage unavailable'))
        return
      }
      wx.chooseImage({
        count: 1,
        sourceType: ['album'],
        sizeType: ['compressed'],
        success: (res) => {
          const paths = res && Array.isArray(res.tempFilePaths) ? res.tempFilePaths : []
          paths[0] ? resolve(paths[0]) : reject(new Error('chooseImage returned no image path'))
        },
        fail: reject,
      })
    })
  },

  async chooseProfileAvatar() {
    // chooseAvatar 是“微信头像选择”开放能力，并不等价于系统相册。
    // 这里的交互目标是点击头像后直接进入真机相册，因此改用 chooseMedia，
    // 并用 chooseImage 兼容旧客户端。整个原生选择过程中不 setData，避免打断手势链。
    if (this._profileAvatarPickerActive || !this._alive) return
    this._profileAvatarPickerActive = true

    try {
      let avatarPath = ''
      let firstError = null

      try {
        avatarPath = await this._chooseMediaFromAlbum()
      } catch (error) {
        if (this._isNativeCancel(error)) return
        firstError = error
        console.warn('[PROFILE_AVATAR] chooseMedia failed, fallback to chooseImage', error)
      }

      if (!avatarPath) {
        try {
          avatarPath = await this._chooseImageFromAlbum()
        } catch (error) {
          if (this._isNativeCancel(error)) return
          console.warn('[PROFILE_AVATAR] chooseImage failed', error)
          throw firstError || error
        }
      }

      if (!this._alive || !avatarPath) return
      this._applyProfileAvatar(avatarPath)
    } catch (error) {
      const message = String((error && (error.errMsg || error.message)) || '')
      console.warn('[PROFILE_AVATAR] album picker failed', error)
      wx.showToast({
        title: /auth|authorize|permission|privacy|scope/i.test(message)
          ? '请允许访问相册后再试'
          : '无法打开相册，请稍后重试',
        icon: 'none',
        duration: 2200,
      })
    } finally {
      this._profileAvatarPickerActive = false
    }
  },

  // Native nickname input must stay as close as possible to WeChat's documented
  // implementation. Do not setData on focus/keyboard/input; rebuilding a controlled
  // nickname input while the IME is attaching can make the host-app nickname chip
  // disappear on some real devices.
  onProfileNicknameInput(e) {
    const detail = (e && e.detail) || {}
    this._profileNicknameDraftRaw = typeof detail.value === 'string' ? detail.value : ''
  },

  _commitProfileNicknameCandidate(rawValue, { scheduleSave = true } = {}) {
    const value = this._normalizeProfileNickname(rawValue)
    if (!value) return false

    const previousDraft = this._normalizeProfileNickname(this.data.profileNickname)
    if (value !== previousDraft) this._profileDraftVersion++

    clearTimeout(this._profileSavedHintTimer)
    this._profileSavedHintTimer = null
    this._profileNicknameDraftRaw = ''
    this.setData({
      profileNickname: value,
      profileSaveState: value !== this._getProfileNickname(this.data.user) ? 'pending' : '',
    }, () => {
      if (scheduleSave) this._scheduleProfileSaveIfReady('nickname')
    })
    return true
  },

  onProfileNicknameChange(e) {
    const detail = (e && e.detail) || {}
    if (typeof detail.value !== 'string') return
    this._commitProfileNicknameCandidate(detail.value)
  },

  onProfileNicknameConfirm(e) {
    const detail = (e && e.detail) || {}
    const rawValue = typeof detail.value === 'string' && detail.value
      ? detail.value
      : this._profileNicknameDraftRaw
    this._commitProfileNicknameCandidate(rawValue)
    try { wx.hideKeyboard && wx.hideKeyboard() } catch (_) {}
  },

  onProfileNicknameBlur(e) {
    const detail = (e && e.detail) || {}
    const rawValue = typeof detail.value === 'string' && detail.value
      ? detail.value
      : this._profileNicknameDraftRaw
    this._commitProfileNicknameCandidate(rawValue)
    this._profileNicknameDraftRaw = ''
  },

  async saveProfile() {
    if (!this._alive) return
    if (this.data.profileSaving) return
    clearTimeout(this._profileAutoSaveTimer)
    clearTimeout(this._profileSavedHintTimer)
    this._profileAutoSaveTimer = null
    this._profileSavedHintTimer = null
    const nickname = this._normalizeProfileNickname(this.data.profileNickname)
    const avatarPath = this.data.profileAvatarPath || ''
    const currentNickname = this._getProfileNickname(this.data.user)
    const nicknameChanged = nickname !== currentNickname
    const avatarChanged = !!avatarPath
    if (!nickname) {
      wx.showToast({ title: '请填写昵称', icon: 'none' })
      return
    }
    if (!nicknameChanged && !avatarChanged) {
      this.setData({ profileSaveState: '' })
      return
    }
    const saveSeq = ++this._profileSaveSeq
    const draftVersionAtStart = this._profileDraftVersion
    this.setData({ profileSaving: true, profileSaveState: 'saving' })
    try {
      const updatedUser = await auth.updateProfile({ nickname, avatarPath })
      if (!this._alive || saveSeq !== this._profileSaveSeq) return
      this._applySavedProfile(updatedUser, nickname, avatarPath, draftVersionAtStart)
    } catch (e) {
      if (!this._alive || saveSeq !== this._profileSaveSeq) return
      this.setData({ profileSaveState: 'error' })
      const message = e && e.message ? e.message : '保存失败，请稍后重试'
      wx.showToast({ title: message, icon: 'none' })
    } finally {
      this._finalizeProfileSave(saveSeq, draftVersionAtStart)
    }
  },

  _applySavedProfile(updatedUser, nickname, avatarPath, draftVersionAtStart) {
    // 保存期间用户仍可重新选头像/改昵称。只清掉本次真正提交的草稿；
    // 若期间已有更新，则保留最新本地草稿并在 finally 后自动续传。
    const latestAvatarPath = this.data.profileAvatarPath || ''
    const latestNickname = this._normalizeProfileNickname(this.data.profileNickname)
    const avatarChangedDuringSave = latestAvatarPath && latestAvatarPath !== avatarPath
    const nicknameChangedDuringSave = latestNickname !== nickname
    const hasNewerDraft = this._profileDraftVersion !== draftVersionAtStart && (avatarChangedDuringSave || nicknameChangedDuringSave)
    const serverAvatar = this._getProfileAvatar(updatedUser)
    const serverNickname = this._getProfileNickname(updatedUser) || nickname
    this.setData({
      user: updatedUser,
      displayName: this.getDisplayName(updatedUser),
      userInitial: this.getUserInitial(updatedUser),
      profileNickname: nicknameChangedDuringSave ? this.data.profileNickname : serverNickname,
      profileAvatarPreview: avatarChangedDuringSave ? this.data.profileAvatarPreview : (serverAvatar || this.data.profileAvatarPreview || ''),
      profileAvatarPath: avatarChangedDuringSave ? latestAvatarPath : '',
      profileSaveState: hasNewerDraft ? 'pending' : 'saved',
    })
    if (!hasNewerDraft) {
      this._profileSavedHintTimer = setTimeout(() => {
        this._profileSavedHintTimer = null
        if (this._alive && this.data.showProfileSheet && !this.data.profileSaving) {
          this.setData({ profileSaveState: '' })
        }
      }, 1500)
    }
  },

  _finalizeProfileSave(saveSeq, draftVersionAtStart) {
    if (!this._alive || saveSeq !== this._profileSaveSeq) return
    this.setData({ profileSaving: false }, () => {
      if (!this._alive || !this.data.showProfileSheet) return
      if (this._profileDraftVersion !== draftVersionAtStart) {
        clearTimeout(this._profileAutoSaveTimer)
        this._profileAutoSaveTimer = setTimeout(() => {
          this._profileAutoSaveTimer = null
          this._scheduleProfileSaveIfReady()
        }, 120)
      }
    })
  },

  measureNavigation() {
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
    const menuLeft = menu && menu.left ? Number(menu.left) : windowWidth - 100
    const verticalGap = Math.max(4, menuTop - statusBarHeight)
    const navContentHeight = menuHeight + verticalGap * 2
    const navHeight = statusBarHeight + navContentHeight
    const navRightPadding = Math.max(102, windowWidth - menuLeft + 8)

    this.setData({
      statusBarHeight,
      navContentHeight,
      navHeight,
      navRightPadding,
    })
  },

  startPrimaryTask() {
    if (!this._authed) {
      this.startGuestTrial()
      return
    }
    // Stage 8 turns the focus card into the first concrete item of today's plan.
    // The practice setup page is still shown (autostart=0), so users can inspect
    // or change the recommendation before starting. If they change its scope,
    // backend plan-token validation simply drops attribution.
    if (this.data.studyHubAvailable && this.data.hubPrimaryTask) {
      this.openHubTaskByData(this.data.hubPrimaryTask)
      return
    }
    const params = this.data.primaryTaskParams || {}
    const query = Object.keys(params)
      .filter(key => params[key] !== undefined && params[key] !== null && params[key] !== '')
      .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(String(params[key]))}`)
      .join('&')
    if (this.data.primaryTaskRoute === 'pomodoro') {
      wx.navigateTo({ url: `/pages/pomodoro/pomodoro${query ? '?' + query : ''}` })
      return
    }
    if (this.data.primaryTaskRoute === 'practice') {
      this.openHubTaskByData({ route: 'practice', route_params: this.data.primaryTaskParams || {} })
      return
    }
    if (this.data.primaryTaskType === 'review') {
      this.goReview()
      return
    }
    this.startRandom()
  },

  startSecondaryTask() {
    if (this.data.guestMode) return
    if (!this._requireLogin('学习报告需要登录后查看。你仍可以浏览公式或试做题目。')) return
    if (this.data.studyHubAvailable) {
      this.goDashboard()
      return
    }
    if (this.data.primaryTaskType === 'review') {
      this.startRandom()
      return
    }
    this.goReview()
  },

  openHubTask(e) {
    const key = e && e.currentTarget && e.currentTarget.dataset
      ? String(e.currentTarget.dataset.taskKey || '')
      : ''
    if (!key) return
    const candidates = []
    if (this.data.hubPrimaryTask) candidates.push(this.data.hubPrimaryTask)
    if (this.data.hubSecondaryTask) candidates.push(this.data.hubSecondaryTask)
    const rawTasks = Array.isArray(this._lastHub && this._lastHub.tasks) ? this._lastHub.tasks : []
    Array.prototype.push.apply(candidates, rawTasks)
    const task = candidates.find(item => item && item.key === key)
    if (task) this.openHubTaskByData(task)
  },

  openHubTaskByData(task) {
    if (!task) return
    if (!this._authed) {
      this.startGuestTrial()
      return
    }
    if (task.route === 'review_today') {
      this.goReview()
      return
    }
    if (task.route !== 'practice') return
    const routeParams = task.route_params && typeof task.route_params === 'object' ? task.route_params : {}
    // Home is the configuration entry: recommendation parameters may preselect
    // subject/mode/count, but the user must still see and confirm the setup page.
    // Other entry points can keep using autostart when they explicitly request it.
    const params = { ...routeParams, autostart: 0, source: routeParams.source || 'home' }
    const query = Object.keys(params)
      .filter(key => params[key] !== undefined && params[key] !== null && params[key] !== '')
      .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(String(params[key]))}`)
      .join('&')
    wx.navigateTo({
      url: `/subpackages/study/practice/practice${query ? '?' + query : ''}`,
    })
  },

  startRandom() {
    if (!this._authed) {
      this.startGuestTrial()
      return
    }
    wx.navigateTo({ url: '/subpackages/study/practice/practice' })
  },
  goWrongBook() {
    wx.navigateTo({ url: `/subpackages/study/wrong-book/wrong-book${this.data.guestMode ? '?guest=1' : ''}` })
  },
  goReview() {
    wx.navigateTo({ url: `/subpackages/study/review-today/review-today${this.data.guestMode ? '?guest=1' : ''}` })
  },
  goDashboard() {
    wx.navigateTo({ url: `/pages/dashboard/dashboard${this.data.guestMode ? '?guest=1' : ''}` })
  },
  goPomodoro() {
    wx.navigateTo({ url: `/pages/pomodoro/pomodoro${this.data.guestMode ? '?guest=1' : ''}` })
  },
  goFormulas() { wx.navigateTo({ url: '/subpackages/formulas/library/index' }) },
  goExams() {
    if (this.data.guestMode) return
    if (!this._requireLogin('真题套卷会保存答题记录，登录后即可开始。')) return
    if (this._examRoutePending) return
    this._examRoutePending = true
    const navigate = () => this._navigateToExams()
    // Home may already be preloading the exam package via preloadRule. Calling
    // loadSubpackage here safely joins/waits for that load, so page creation does
    // not race the package injection. It also keeps rapid taps from creating two
    // competing webviews, which can surface as routeDone/webviewId warnings.
    if (typeof wx.loadSubpackage !== 'function') {
      navigate()
      return
    }
    try {
      wx.loadSubpackage({
        name: 'exam',
        success: navigate,
        fail: (error) => {
          console.warn('[EXAM_ROUTE] subpackage preload failed; falling back to navigateTo', error && (error.errMsg || error.message || error))
          navigate()
        },
      })
    } catch (error) {
      console.warn('[EXAM_ROUTE] loadSubpackage unavailable; falling back to navigateTo', error && (error.errMsg || error.message || error))
      navigate()
    }
  },

  _navigateToExams() {
    if (this._examNavigated) return
    if (!this._alive || !this._visible) {
      this._examRoutePending = false
      return
    }
    this._examNavigated = true
    wx.navigateTo({
      url: '/subpackages/exam/paper-list/index',
      fail: (error) => {
        this._examRoutePending = false
        this._examNavigated = false
        console.warn('[EXAM_ROUTE] navigateTo failed', error && (error.errMsg || error.message || error))
      },
      complete: () => {
        // navigateTo success will hide Home. If routing fails while Home stays visible,
        // release the guard after the framework has finished the current route turn.
        setTimeout(() => {
          if (this._alive && this._visible) {
            this._examRoutePending = false
            this._examNavigated = false
          }
        }, 300)
      },
    })
  },
  goStudyPlan() {
    if (this.data.showGoalPicker) this.setData({ showGoalPicker: false })
    wx.navigateTo({ url: `/subpackages/study/study-plan/index${this.data.guestMode ? '?guest=1' : ''}` })
  },
  openMasterySubject(event) {
    if (this.data.guestMode) return
    if (!this._requireLogin('知识点掌握度来自你的学习记录，登录后即可查看。')) return
    const subjectId = Number(event && event.currentTarget && event.currentTarget.dataset.subjectId)
    if (!subjectId) return
    wx.navigateTo({ url: `/subpackages/knowledge/knowledge-subject/index?subject_id=${subjectId}` })
  },

  onHide() {
    this._visible = false
    this._showSeq++
    this._growthSeq++
    this._clearAnimTimer()

    // 系统头像面板、相册或其他原生 UI 都可能触发页面 hide。
    // 这里不能 setData 清理资料弹层，否则会在开放能力回调前重建节点。
    this._profileNicknameDraftRaw = ''
  },

  onUnload() {
    this._alive = false
    this._visible = false
    this._showSeq++
    this._growthSeq++
    this._profileSaveSeq++
    this._clearAnimTimer()
    clearTimeout(this._profileAutoSaveTimer)
    clearTimeout(this._profileSavedHintTimer)
    this._profileAutoSaveTimer = null
    this._profileSavedHintTimer = null
  },
})

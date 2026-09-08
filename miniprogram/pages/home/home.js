const auth = require('../../utils/auth')
const api = require('../../utils/api')
const storage = require('../../utils/storage')
const { getChinaWallParts } = require('../../utils/china-time')

const TODAY_GOAL_TOTAL = 30
const TODAY_GOAL_KEY = 'home_today_goal_total'
const GOAL_OPTIONS = [10, 20, 30, 50]

Page({
  data: {
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
    primaryTaskTitle: `完成今日 ${TODAY_GOAL_TOTAL} 道 408 练习`,
    primaryTaskDesc: '先完成一组 408 练习建立节奏，之后再根据结果安排复习。',
    primaryTaskAction: '开始 408 练习',
    secondaryTaskAction: '查看复习计划',
    studyHubAvailable: false,
    studyHubFallback: false,
    hubPrimaryTask: null,
    hubSecondaryTask: null,
    hubTasks: [],
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
    missionText: '完成一组 408 练习，点亮今日目标',
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
  _animTimer: null,
  _profileAutoSaveTimer: null,
  _profileSavedHintTimer: null,
  _profileDraftVersion: 0,
  _profileNicknameDraftRaw: '',

  onLoad() {
    this._alive = true
    this.measureNavigation()
    this.detectRuntime()
  },

  async onShow() {
    this._alive = true
    this._visible = true

    // chooseAvatar 会打开微信原生选择界面，返回页面时会再次触发 onShow。
    // 资料弹层打开期间绝不做 setData / 用户同步，避免在原生开放能力完成回调前
    // 重建 button/input 节点，导致头像回调丢失或 nickname 快捷填入条被卸载。
    if (this.data.showProfileSheet) return

    const showSeq = ++this._showSeq
    this._authed = auth.isLoggedIn()
    this._isAdmin = this._authed ? auth.isAdmin() : false
    const localUser = auth.getUser() || {}
    const basePatch = {
      user: localUser,
      displayName: this.getDisplayName(localUser),
      userInitial: this.getUserInitial(localUser),
      greeting: this.getGreeting(),
      dateStr: this.getDateStr(),
      motto: this.getMotto(),
    }
    if (!this._hasGrowthSnapshot) {
      Object.assign(basePatch, {
        _animStreakDays: 0,
        _animGoalDone: 0,
        _animLevelProgress: 0,
        ...this.getGrowthFallback(),
      })
    }
    this.setData(basePatch)
    if (!this._authed) return

    try {
      const syncedUser = await auth.syncCurrentUser()
      if (!this._alive || !this._visible || showSeq !== this._showSeq) return
      if (syncedUser) {
        this._isAdmin = auth.isAdmin()
        this.setData({
          user: syncedUser,
          displayName: this.getDisplayName(syncedUser),
          userInitial: this.getUserInitial(syncedUser),
        })
      }
    } catch (e) {
      // Profile/permission sync is helpful but must not block the home dashboard.
      // A transient /users/me failure should still allow growth data to load.
      console.error('同步用户权限失败', e)
      if (!this._alive || !this._visible || showSeq !== this._showSeq) return
      this._authed = auth.isLoggedIn()
      if (!this._authed) return
    }

    // 个人资料仅在用户主动点击首页头像入口时打开，不在首页自动弹出。
    await this.loadGrowthSnapshot(showSeq)
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
    if (!this._authed) return

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

      const requireAuthorization = () => {
        try {
          wx.requirePrivacyAuthorize({
            success: () => finish(true),
            fail: (error) => {
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
          })
        } catch (error) {
          console.warn('[PROFILE_PRIVACY] requirePrivacyAuthorize unavailable', error)
          finish(true)
        }
      }

      if (typeof wx.getPrivacySetting !== 'function') {
        requireAuthorization()
        return
      }

      try {
        wx.getPrivacySetting({
          success: (result) => {
            if (result && result.needAuthorization) {
              requireAuthorization()
            } else {
              finish(true)
            }
          },
          fail: () => requireAuthorization(),
        })
      } catch (_) {
        requireAuthorization()
      }
    })
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
      const info = wx.getSystemInfoSync ? wx.getSystemInfoSync() : {}
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
    } catch (e) {
      if (!this._alive || saveSeq !== this._profileSaveSeq) return
      this.setData({ profileSaveState: 'error' })
      const message = e && e.message ? e.message : '保存失败，请稍后重试'
      wx.showToast({ title: message, icon: 'none' })
    } finally {
      if (this._alive && saveSeq === this._profileSaveSeq) {
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
      }
    }
  },

  measureNavigation() {
    let statusBarHeight = 20
    let windowWidth = 375
    try {
      const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
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

  async loadGrowthSnapshot(showSeq = this._showSeq) {
    if (!this._alive || !this._visible) return
    const requestSeq = ++this._growthSeq
    this._clearAnimTimer()
    try {
      // Avoid array destructuring here. Some WeChat DevTools/SWC builds emit
      // @swc/runtime/_sliced_to_array, whose transitive _array_with_holes
      // helper can be omitted from the mini-program package and crash at runtime.
      const growthResponses = await Promise.all([
        api.get('/stats/dashboard'),
        api.get('/stats/growth').catch(() => null),
        api.get('/study-hub/overview').catch((error) => {
          console.warn('加载 408 智能学习中心失败，回退基础首页', error)
          return null
        }),
        api.get('/study-plan/overview').catch((error) => {
          console.warn('加载 408 长期学习计划失败', error)
          return null
        }),
      ])
      const dashRes = growthResponses[0]
      const growthRes = growthResponses[1]
      const hubRes = growthResponses[2]
      const planRes = growthResponses[3]
      if (
        !this._alive ||
        !this._visible ||
        requestSeq !== this._growthSeq ||
        showSeq !== this._showSeq
      ) return

      const overview = (dashRes && dashRes.overview) || {}
      const growth = growthRes || null
      this._lastGrowth = growth
      const snapshot = this.buildGrowthSnapshot(overview, growth, hubRes, planRes)
      this._hasGrowthSnapshot = true
      this.setData(snapshot, () => {
        if (this._alive && this._visible && requestSeq === this._growthSeq) {
          this._animateNumbers()
        }
      })
    } catch (e) {
      if (
        !this._alive ||
        !this._visible ||
        requestSeq !== this._growthSeq ||
        showSeq !== this._showSeq
      ) return
      console.error('加载成长数据失败', e)
    }
  },

  /* 统一数字动画调度：80ms 间隔，一次 setData 更新三个字段 */
  _animateNumbers() {
    this._clearAnimTimer()
    const targets = this._growthTargets
    const from = {
      streakDays: this.data._animStreakDays,
      goalDone: this.data._animGoalDone,
      levelProgress: this.data._animLevelProgress,
    }
    const to = {
      streakDays: targets.streakDays,
      goalDone: targets.todayGoalDone,
      levelProgress: targets.levelProgress,
    }
    if (from.streakDays === to.streakDays && from.goalDone === to.goalDone && from.levelProgress === to.levelProgress) return

    const durations = { streakDays: 600, goalDone: 600, levelProgress: 500 }
    const startTime = Date.now()

    const tick = () => {
      if (!this._alive || !this._visible) {
        this._animTimer = null
        return
      }
      const elapsed = Date.now() - startTime
      const data = {}
      let allDone = true

      const updateField = (key, fromVal, toVal, duration) => {
        if (fromVal === toVal) return
        const p = Math.min(elapsed / duration, 1)
        const eased = 1 - Math.pow(1 - p, 3)
        const current = Math.round(fromVal + (toVal - fromVal) * eased)
        data[key] = Math.min(toVal, Math.max(Math.min(fromVal, toVal), current))
        if (p < 1) allDone = false
      }

      updateField('_animStreakDays', from.streakDays, to.streakDays, durations.streakDays)
      updateField('_animGoalDone', from.goalDone, to.goalDone, durations.goalDone)
      updateField('_animLevelProgress', from.levelProgress, to.levelProgress, durations.levelProgress)

      if (Object.keys(data).length > 0) this.setData(data)

      if (!allDone) {
        this._animTimer = setTimeout(tick, 80)
      } else {
        this.setData({
          _animStreakDays: to.streakDays,
          _animGoalDone: to.goalDone,
          _animLevelProgress: to.levelProgress,
        })
        this._animTimer = null
      }
    }

    this._animTimer = setTimeout(tick, 80)
  },

  getGrowthFallback() {
    const todayGoalTotal = this.getStoredTodayGoal()
    const levelMeta = this.getLevelMeta(0)
    return {
      studyLevel: 'Lv1 起步',
      levelProgress: 0,
      todayGoalTotal,
      ...this.getPrimaryTaskSnapshot(0, todayGoalTotal, 0),
      ...this.getHubDisplaySnapshot(null),
      ...this.getStudyPlanDisplaySnapshot(null),
      expText: levelMeta.expText,
      nextLevelText: levelMeta.nextLevelText,
      dailyBoostText: this.getDailyBoostText(0, todayGoalTotal, 0),
      badgeList: this.getBadgeList(0, 0, 0),
      badgeTitle: '今日待点亮',
      missionText: '完成一组 408 练习，点亮今日目标',
    }
  },

  buildGrowthSnapshot(overview, growth, hub, plan) {
    this._lastOverview = overview || {}
    this._lastHub = hub || null
    this._lastPlan = plan || null
    const streakDays = this.toNonNegativeInt(overview.consecutive_days)
    const hubTodayQuestions = hub && hub.scope_ready !== false ? hub.today_question_count : null
    const todayGoalDone = this.toNonNegativeInt(hubTodayQuestions != null ? hubTodayQuestions : overview.today_questions)
    const totalQuestions = this.toNonNegativeInt(overview.total_questions)
    const hubReviewRemaining = hub && hub.review ? hub.review.remaining_count : null
    const dueReviewCount = this.toNonNegativeInt(hubReviewRemaining != null ? hubReviewRemaining : overview.due_review_count)
    const todayGoalTotal = this.getStoredTodayGoal()
    const levelProgress = Math.min(100, Math.round((todayGoalDone / todayGoalTotal) * 100))
    const hubDisplay = this.getHubDisplaySnapshot(hub)
    const planDisplay = this.getStudyPlanDisplaySnapshot(plan)
    const taskSnapshot = hubDisplay.studyHubAvailable
      ? this.getHubPrimaryTaskSnapshot(hub, todayGoalDone, todayGoalTotal)
      : this.getPrimaryTaskSnapshot(todayGoalDone, todayGoalTotal, dueReviewCount)

    this._growthTargets = { streakDays, todayGoalDone, levelProgress }

    if (growth) {
      const topBadges = (growth.badges || []).slice(0, 3)
      return {
        studyLevel: growth.level_title || 'Lv1 起步',
        levelProgress,
        todayGoalTotal,
        ...taskSnapshot,
        ...hubDisplay,
        ...planDisplay,
        expText: `${growth.exp_current || 0} / ${growth.exp_to_next || 0} EXP`,
        nextLevelText: growth.level_progress_pct >= 100
          ? '已满级，继续保持题感'
          : `距离下一级还差 ${Math.max(0, (growth.exp_to_next || 0) - (growth.exp_current || 0))} EXP`,
        dailyBoostText: growth.daily_boost || this.getDailyBoostText(todayGoalDone, todayGoalTotal, streakDays),
        badgeList: topBadges.map(b => ({
          key: b.key, title: b.title, desc: b.unlocked ? '已点亮' : b.desc, unlocked: b.unlocked
        })),
        badgeTitle: streakDays >= 30 ? '连续30天徽章' : streakDays >= 7 ? '连续7天徽章' : topBadges.some(b => b.unlocked) ? '徽章进行中' : '今日待点亮',
        missionText: this.getMissionText(todayGoalDone, todayGoalTotal, dueReviewCount),
      }
    }

    const levelMeta = this.getLevelMeta(totalQuestions)
    return {
      studyLevel: levelMeta.studyLevel,
      levelProgress,
      todayGoalTotal,
      ...taskSnapshot,
      ...hubDisplay,
      ...planDisplay,
      expText: levelMeta.expText,
      nextLevelText: levelMeta.nextLevelText,
      dailyBoostText: this.getDailyBoostText(todayGoalDone, todayGoalTotal, streakDays),
      badgeList: this.getBadgeList(streakDays, totalQuestions, levelProgress),
      badgeTitle: this.getBadgeTitle(streakDays, levelProgress),
      missionText: this.getMissionText(todayGoalDone, todayGoalTotal, dueReviewCount),
    }
  },

  getStudyPlanDisplaySnapshot(plan) {
    if (!plan || !plan.configured || !plan.plan) {
      return {
        studyPlanConfigured: false,
        planDaysRemaining: 0,
        planPhaseLabel: '',
        planTargetDateText: '',
        planTodayText: '尚未设置长期计划',
        planWeeklyText: '',
        planProgressPercent: 0,
        planPrimaryText: '设置目标日期后，自动组织复习、弱项、新题与真题选择题',
      }
    }
    const countdown = plan.countdown || {}
    const weekly = plan.weekly || {}
    const today = plan.today || {}
    const allocations = Array.isArray(today.allocations) ? today.allocations : []
    const primary = allocations.find(item => item && item.category === today.primary_category) || null
    const targetDate = String(countdown.target_date || plan.plan.target_date || '')
    return {
      studyPlanConfigured: true,
      planDaysRemaining: this.toNonNegativeInt(countdown.days_remaining),
      planPhaseLabel: String(countdown.phase_label || ''),
      planTargetDateText: targetDate,
      planTodayText: today.is_rest_day
        ? '本周目标已达成，今天建议轻量复盘'
        : `今日 ${this.toNonNegativeInt(today.completed_minutes)} / ${this.toNonNegativeInt(today.target_minutes)} 分钟`,
      planWeeklyText: `本周 ${this.toNonNegativeInt(weekly.active_days)} / ${this.toNonNegativeInt(weekly.target_days)} 天`,
      planProgressPercent: Math.max(0, Math.min(100, this.toNonNegativeInt(today.completion_percent))),
      planPrimaryText: primary && primary.title ? String(primary.title) : '今天的计划已完成或暂无强制任务',
    }
  },

  getHubDisplaySnapshot(hub) {
    const available = !!(hub && hub.scope_ready !== false && hub.primary_task)
    if (!available) {
      return {
        studyHubAvailable: false,
        studyHubFallback: false,
        hubPrimaryTask: null,
        hubSecondaryTask: null,
        hubTasks: [],
        subjectMastery: [],
      }
    }

    const allTasks = Array.isArray(hub.tasks) ? hub.tasks : []
    const primaryKey = hub.primary_task && hub.primary_task.key
    const secondaryRaw = allTasks.find(task => task && task.key !== primaryKey) || null
    const taskTypeMeta = {
      review: { eyebrow: '记忆优先', icon: 'R' },
      weakness: { eyebrow: '弱项强化', icon: 'W' },
      hard_questions: { eyebrow: '困难题重练', icon: 'H' },
      knowledge_path: { eyebrow: '知识路径', icon: 'P' },
      smart_practice: { eyebrow: '智能新题', icon: 'S' },
    }
    const displayTasks = allTasks
      .filter(task => task && task.key !== primaryKey)
      .slice(0, 4)
      .map((task, index) => {
        const meta = taskTypeMeta[task.task_type] || { eyebrow: '今日任务', icon: 'T' }
        const q = this.toNonNegativeInt(task.estimated_question_count)
        const m = this.toNonNegativeInt(task.estimated_minutes)
        return {
          key: task.key,
          taskType: task.task_type,
          priorityText: String(index + 2).padStart(2, '0'),
          eyebrow: meta.eyebrow,
          icon: meta.icon,
          title: task.title || '继续 408 学习',
          reason: task.reason || '',
          actionLabel: task.action_label || '开始',
          metaText: q > 0 ? `约 ${q} 题 · ${m || 1} 分钟` : '按当前学习状态推荐',
          route: task.route || '',
          routeParams: task.route_params || {},
        }
      })

    const subjectMastery = (Array.isArray(hub.subject_mastery) ? hub.subject_mastery : []).map(item => {
      const hasData = !!(item && item.data_available && item.mastery_score != null)
      const score = hasData ? Math.max(0, Math.min(100, Math.round(Number(item.mastery_score) || 0))) : 0
      return {
        subjectId: Number(item.subject_id),
        subjectCode: String(item.subject_code || ''),
        subjectName: String(item.subject_name || ''),
        hasData,
        score,
        scoreText: hasData ? `${score}%` : '--',
        barWidth: hasData ? score : 0,
        attemptCount: this.toNonNegativeInt(item.attempt_count),
        statusText: hasData ? '综合掌握' : '数据不足',
      }
    })

    return {
      studyHubAvailable: true,
      studyHubFallback: !!hub.fallback_used,
      hubPrimaryTask: hub.primary_task,
      hubSecondaryTask: secondaryRaw,
      hubTasks: displayTasks,
      subjectMastery,
    }
  },

  getHubPrimaryTaskSnapshot(hub, todayGoalDone, todayGoalTotal) {
    const task = hub && hub.primary_task ? hub.primary_task : null
    if (!task) return this.getPrimaryTaskSnapshot(todayGoalDone, todayGoalTotal, 0)
    const remainingCount = Math.max(0, todayGoalTotal - todayGoalDone)
    const dueReviewCount = this.toNonNegativeInt(hub && hub.review && hub.review.remaining_count)
    const priority = this.toNonNegativeInt(task.priority) || 1
    const secondary = Array.isArray(hub.tasks)
      ? hub.tasks.find(item => item && item.key !== task.key)
      : null
    return {
      dueReviewCount,
      remainingCount,
      primaryTaskType: task.task_type || 'practice',
      primaryTaskKicker: `SMART STUDY · 优先级 ${String(priority).padStart(2, '0')}`,
      primaryTaskTitle: task.title || '继续 408 今日学习',
      primaryTaskDesc: task.reason || '根据当前学习状态安排下一项任务。',
      primaryTaskAction: task.action_label || '开始学习',
      secondaryTaskAction: secondary ? (secondary.action_label || '下一项任务') : '查看学习报告',
    }
  },

  getPrimaryTaskSnapshot(todayGoalDone, todayGoalTotal, dueReviewCount) {
    const remainingCount = Math.max(0, todayGoalTotal - todayGoalDone)

    if (dueReviewCount > 0) {
      return {
        dueReviewCount,
        remainingCount,
        primaryTaskType: 'review',
        primaryTaskKicker: 'MEMORY FIRST · 优先级 01',
        primaryTaskTitle: `先复习 ${dueReviewCount} 道 408 到期错题`,
        primaryTaskDesc: '这些 408 错题已进入复习窗口。先巩固记忆，再开始新练习，效率会更高。',
        primaryTaskAction: '开始今日复习',
        secondaryTaskAction: '先做新题',
      }
    }

    if (remainingCount > 0) {
      return {
        dueReviewCount,
        remainingCount,
        primaryTaskType: 'practice',
        primaryTaskKicker: 'TODAY PLAN · 优先级 01',
        primaryTaskTitle: `完成剩余 ${remainingCount} 道 408 练习`,
        primaryTaskDesc: `今天已完成 ${todayGoalDone} 道 408 练习。保持稳定节奏即可，不必一次全部做完。`,
        primaryTaskAction: '开始 408 练习',
        secondaryTaskAction: '查看复习计划',
      }
    }

    return {
      dueReviewCount,
      remainingCount,
      primaryTaskType: 'complete',
      primaryTaskKicker: 'TODAY COMPLETE · 今日已完成',
      primaryTaskTitle: '今天的 408 核心任务已完成',
      primaryTaskDesc: '节奏已经守住。可以用少量 408 新题保持手感，也可以安心结束今天的学习。',
      primaryTaskAction: '再练一组',
      secondaryTaskAction: '查看复习记录',
    }
  },

  getStoredTodayGoal() {
    const stored = Number(storage.get(TODAY_GOAL_KEY))
    return GOAL_OPTIONS.includes(stored) ? stored : TODAY_GOAL_TOTAL
  },

  toggleGoalPicker() {
    this.setData({ showGoalPicker: !this.data.showGoalPicker })
  },

  selectTodayGoal(e) {
    const goal = Number(e.currentTarget.dataset.goal)
    if (!GOAL_OPTIONS.includes(goal)) return
    storage.set(TODAY_GOAL_KEY, goal)
    this.setData({
      _animStreakDays: 0,
      _animGoalDone: 0,
      _animLevelProgress: 0,
      ...this.buildGrowthSnapshot(this._lastOverview || {}, this._lastGrowth, this._lastHub, this._lastPlan),
      showGoalPicker: false,
    })
    this._animateNumbers()
  },

  getLevelMeta(totalQuestions) {
    const levels = [
      { level: 1, title: 'Lv1 起步', min: 0, next: 50 },
      { level: 2, title: 'Lv2 坚持者', min: 50, next: 200 },
      { level: 3, title: 'Lv3 刷题达人', min: 200, next: 500 },
      { level: 4, title: 'Lv4 高效进阶', min: 500, next: 1000 },
      { level: 5, title: 'Lv5 上岸冲刺', min: 1000, next: null },
    ]
    const current = levels.slice().reverse().find(item => totalQuestions >= item.min) || levels[0]
    if (!current.next) {
      return {
        studyLevel: current.title,
        expText: `${totalQuestions} EXP`,
        nextLevelText: '已进入冲刺等级，继续保持题感',
      }
    }
    const currentExp = Math.max(0, totalQuestions - current.min)
    const nextExp = current.next - current.min
    return {
      studyLevel: current.title,
      expText: `${currentExp} / ${nextExp} EXP`,
      nextLevelText: `距离 Lv${current.level + 1} 还差 ${Math.max(0, current.next - totalQuestions)} 题`,
    }
  },

  getDailyBoostText(todayGoalDone, todayGoalTotal, streakDays) {
    const remaining = Math.max(0, todayGoalTotal - todayGoalDone)
    if (remaining === 0) return '今日目标已经完成。稳定结束，比临时加量更有利于长期坚持。'
    if (streakDays >= 7) return `你已经连续学习 ${streakDays} 天。再完成 ${remaining} 题，就能守住今天的节奏。`
    return `不需要追求一次做完；先完成一组，再决定是否继续。今天还剩 ${remaining} 题。`
  },

  getBadgeList(streakDays, totalQuestions, levelProgress) {
    return [
      { key: 'today', title: '今日目标', desc: '完成每日题量', unlocked: levelProgress >= 100 },
      { key: 'streak7', title: '连续 7 天', desc: '保持复习节奏', unlocked: streakDays >= 7 },
      { key: 'hundred', title: '百题积累', desc: '累计完成 100 题', unlocked: totalQuestions >= 100 },
    ]
  },

  getStudyLevel(totalQuestions) {
    return this.getLevelMeta(totalQuestions).studyLevel
  },

  getBadgeTitle(streakDays, levelProgress) {
    if (levelProgress >= 100) return '今日目标已完成'
    if (streakDays >= 30) return '连续 30 天徽章'
    if (streakDays >= 15) return '连续 15 天徽章'
    if (streakDays >= 7) return '连续 7 天徽章'
    if (streakDays > 0) return '坚持学习徽章'
    return '今日待点亮'
  },

  getMissionText(todayGoalDone, todayGoalTotal, dueReviewCount) {
    const remaining = Math.max(0, todayGoalTotal - todayGoalDone)
    if (remaining === 0) {
      if (dueReviewCount > 0) return `目标已完成，仍有 ${dueReviewCount} 道到期复习`
      return '今日目标已完成，保持节奏'
    }
    if (dueReviewCount > 0) return `先处理到期复习，再完成 ${remaining} 道新题`
    return `再完成 ${remaining} 题，点亮今日目标`
  },

  getDisplayName(user) {
    const name = user && (user.nickName || user.nickname || user.name)
    return name ? String(name).trim().slice(0, 8) : '研友'
  },

  getUserInitial(user) {
    const name = this.getDisplayName(user)
    return name ? name.slice(0, 1) : '研'
  },

  toNonNegativeInt(value) {
    const n = Number(value)
    if (!Number.isFinite(n) || n < 0) return 0
    return Math.round(n)
  },

  getGreeting() {
    const h = getChinaWallParts(Date.now()).hour
    if (h < 6) return '夜深了'
    if (h < 9) return '早上好'
    if (h < 12) return '上午好'
    if (h < 14) return '中午好'
    if (h < 18) return '下午好'
    return '晚上好'
  },

  getMotto() {
    const h = getChinaWallParts(Date.now()).hour
    if (h < 6) return '休息也是学习的一部分，明天再战'
    if (h < 9) return '清晨是记忆的黄金时间'
    if (h < 12) return '开始今天的学习计划吧'
    if (h < 14) return '午后小憩一下，学习更高效'
    if (h < 18) return '保持专注，坚持就是胜利'
    return '完成今日计划，收获满满成就感'
  },

  getDateStr() {
    const d = getChinaWallParts(Date.now())
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.month}月${d.day}日 · 星期${week[d.weekday]}`
  },

  startPrimaryTask() {
    if (this.data.studyHubAvailable && this.data.hubPrimaryTask) {
      this.openHubTaskByData(this.data.hubPrimaryTask)
      return
    }
    if (this.data.primaryTaskType === 'review') {
      this.goReview()
      return
    }
    this.startRandom()
  },

  startSecondaryTask() {
    if (this.data.studyHubAvailable && this.data.hubSecondaryTask) {
      this.openHubTaskByData(this.data.hubSecondaryTask)
      return
    }
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
    candidates.push(...rawTasks)
    const task = candidates.find(item => item && item.key === key)
    if (task) this.openHubTaskByData(task)
  },

  openHubTaskByData(task) {
    if (!task) return
    if (task.route === 'review_today') {
      this.goReview()
      return
    }
    if (task.route !== 'practice') return
    const params = task.route_params && typeof task.route_params === 'object' ? task.route_params : {}
    const query = Object.keys(params)
      .filter(key => params[key] !== undefined && params[key] !== null && params[key] !== '')
      .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(String(params[key]))}`)
      .join('&')
    wx.navigateTo({
      url: `/subpackages/study/practice/practice${query ? '?' + query : ''}`,
    })
  },

  drawSubjectPie() {
    const subjectPieData = Array.isArray(this.data.subjectPieData) ? this.data.subjectPieData : []
    if (!subjectPieData.length) return
    const query = wx.createSelectorQuery().in(this)
    query.select('#subject-pie-canvas').boundingClientRect(rect => {
      if (!rect || !rect.width || !rect.height) return
      const canvasSize = Math.min(rect.width, rect.height)
      const ctx = wx.createCanvasContext('subject-pie-canvas', this)
      const center = canvasSize / 2
      const radius = center - 10
      ctx.clearRect(0, 0, canvasSize, canvasSize)
      subjectPieData.forEach(item => {
        const start = (item._startAngle - 90) * Math.PI / 180
        const end = (item._endAngle - 90) * Math.PI / 180
        ctx.beginPath()
        ctx.moveTo(center, center)
        ctx.setFillStyle(item._color)
        ctx.arc(center, center, radius, start, end)
        ctx.closePath()
        ctx.fill()
      })
      ctx.draw()
    }).exec()
  },

  startRandom() { wx.navigateTo({ url: '/subpackages/study/practice/practice' }) },
  goWrongBook() { wx.navigateTo({ url: '/subpackages/study/wrong-book/wrong-book' }) },
  goReview() { wx.navigateTo({ url: '/subpackages/study/review-today/review-today' }) },
  goDashboard() { wx.navigateTo({ url: '/pages/dashboard/dashboard' }) },
  goPomodoro() { wx.navigateTo({ url: '/pages/pomodoro/pomodoro' }) },
  goFormulas() { wx.navigateTo({ url: '/subpackages/formulas/library/index' }) },
  goExams() { wx.navigateTo({ url: '/subpackages/exam/paper-list/index' }) },
  goStudyPlan() { wx.navigateTo({ url: '/subpackages/study/study-plan/index' }) },
  goKnowledgeMap() { wx.navigateTo({ url: '/subpackages/study/knowledge-map/index' }) },
  goKnowledgeMapSubject(event) {
    const subjectId = Number(event && event.currentTarget && event.currentTarget.dataset.subjectId)
    if (!subjectId) return this.goKnowledgeMap()
    wx.navigateTo({ url: `/subpackages/study/knowledge-subject/index?subject_id=${subjectId}` })
  },

  _clearAnimTimer() {
    if (this._animTimer) {
      clearTimeout(this._animTimer)
      this._animTimer = null
    }
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

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
    profileNicknameRejected: false,
    profileSaving: false,
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
    primaryTaskAction: '开始今日练习',
    secondaryTaskAction: '查看复习计划',

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
  _animTimer: null,
  _profilePromptTimer: null,
  _profileAutoSaveTimer: null,
  _profilePrompted: false,

  onLoad() {
    this._alive = true
    this.measureNavigation()
    this.detectRuntime()
  },

  async onShow() {
    this._alive = true
    this._visible = true
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

    let profileUser = localUser
    try {
      const syncedUser = await auth.syncCurrentUser()
      if (!this._alive || !this._visible || showSeq !== this._showSeq) return
      if (syncedUser) {
        profileUser = syncedUser
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

    this._maybePromptProfile(profileUser)
    await this.loadGrowthSnapshot(showSeq)
  },

  _isProfileSetupComplete(user) {
    const profile = user || {}
    return !!String(profile.nickname || '').trim() && !!String(profile.avatar_url || '').trim()
  },

  _maybePromptProfile(user) {
    if (this._profilePrompted || this._isProfileSetupComplete(user)) return
    this._profilePrompted = true
    clearTimeout(this._profilePromptTimer)
    this._profilePromptTimer = setTimeout(() => {
      this._profilePromptTimer = null
      if (!this._alive || !this._visible) {
        // The prompt never became visible; allow the next onShow to schedule it.
        this._profilePrompted = false
        return
      }
      if (!this.data.showProfileSheet && this._authed) this.openProfileSheet()
    }, 260)
  },

  openProfileSheet() {
    if (!this._authed) return
    const user = this.data.user || auth.getUser() || {}
    this.setData({
      showProfileSheet: true,
      profileNickname: user.nickname || '',
      profileAvatarPreview: user.avatar_url || '',
      profileAvatarPath: '',
      profileNicknameRejected: false,
    })
  },

  closeProfileSheet() {
    if (this.data.profileSaving) return
    clearTimeout(this._profileAutoSaveTimer)
    this._profileAutoSaveTimer = null
    this.setData({
      showProfileSheet: false,
      profileAvatarPath: '',
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

  _applyProfileAvatar(avatarPath) {
    if (!avatarPath) return
    this.setData({
      profileAvatarPreview: avatarPath,
      profileAvatarPath: avatarPath,
    })
  },

  onChooseAvatar(e) {
    const avatarPath = e && e.detail && e.detail.avatarUrl
    if (!avatarPath) return
    this._applyProfileAvatar(avatarPath)
  },

  async chooseAvatarInDevtools() {
    if (this.data.profileSaving) return
    try {
      const res = await wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album'],
        sizeType: ['compressed'],
      })
      if (!this._alive) return
      const file = res && Array.isArray(res.tempFiles) ? res.tempFiles[0] : null
      const avatarPath = file && (file.tempFilePath || file.path)
      if (avatarPath) this._applyProfileAvatar(avatarPath)
    } catch (error) {
      // 开发者工具取消选择属于正常用户操作，不记录为错误。
      if (this._isNativeCancel(error)) return
      console.warn('开发者工具头像选择失败', error)
      wx.showToast({ title: '头像选择失败，请重试', icon: 'none' })
    }
  },

  onProfileNicknameInput(e) {
    this.setData({
      profileNickname: (e && e.detail && e.detail.value) || '',
      profileNicknameRejected: false,
    })
  },


  onProfileNicknameReview(e) {
    const rejected = !!(e && e.detail && e.detail.pass === false)
    this.setData({ profileNicknameRejected: rejected })
    if (rejected) wx.showToast({ title: '该昵称暂不可使用，请修改后重试', icon: 'none' })
  },

  onNativeProfileChange(e) {
    if (this.data.profileSaving) return
    const detail = (e && e.detail) || {}
    const userInfo = detail.userInfo || {}
    const field = String(detail.field || '')
    const nickname = String(userInfo.nickname || '').trim().replace(/\s+/g, ' ')
    const avatar = String(userInfo.avatar || '')
    const storedAvatar = String((this.data.user && this.data.user.avatar_url) || '')
    const nextAvatarPath = avatar && avatar !== storedAvatar ? avatar : this.data.profileAvatarPath

    this.setData({
      profileNickname: nickname,
      profileAvatarPreview: avatar || this.data.profileAvatarPreview,
      profileAvatarPath: nextAvatarPath || '',
      profileNicknameRejected: false,
    })

    // 首次资料需要头像 + 昵称两步都完成，随后自动保存并关闭弹层。
    // 已经完整保存过资料的用户，修改任一项时直接自动保存。
    const profileAlreadyCompleted = this._isProfileSetupComplete(this.data.user)
    const hasAvatar = !!(nextAvatarPath || storedAvatar || this.data.profileAvatarPreview)
    const firstProfileHasBoth = !profileAlreadyCompleted && !!nickname && hasAvatar
    const existingProfileChanged = profileAlreadyCompleted && !!nickname && (field === 'nickname' || field === 'avatar')
    if (firstProfileHasBoth || existingProfileChanged) {
      clearTimeout(this._profileAutoSaveTimer)
      this._profileAutoSaveTimer = setTimeout(() => {
        this._profileAutoSaveTimer = null
        if (this._alive) this.saveProfile()
      }, 120)
    }
  },

  onNativeProfileError(e) {
    const detail = (e && e.detail) || {}
    const code = String(detail.code || '')
    const message = String(detail.message || '微信资料选择失败，请重试')
    if (code === 'NICKNAME_REVIEW_REJECTED') {
      this.setData({ profileNicknameRejected: true })
    }
    wx.showToast({ title: message, icon: 'none' })
  },

  async saveProfile() {
    if (this.data.profileSaving || !this._alive) return
    clearTimeout(this._profileAutoSaveTimer)
    this._profileAutoSaveTimer = null
    const nickname = String(this.data.profileNickname || '').trim().replace(/\s+/g, ' ')
    if (!nickname) {
      wx.showToast({ title: '请填写昵称', icon: 'none' })
      return
    }
    if (this.data.profileNicknameRejected) {
      wx.showToast({ title: '请修改昵称后再保存', icon: 'none' })
      return
    }

    const saveSeq = ++this._profileSaveSeq
    this.setData({ profileSaving: true })
    try {
      const updatedUser = await auth.updateProfile({
        nickname,
        avatarPath: this.data.profileAvatarPath || '',
      })
      if (!this._alive || saveSeq !== this._profileSaveSeq) return
      this.setData({
        user: updatedUser,
        displayName: this.getDisplayName(updatedUser),
        userInitial: this.getUserInitial(updatedUser),
        showProfileSheet: false,
        profileNickname: updatedUser.nickname || '',
        profileAvatarPreview: updatedUser.avatar_url || '',
        profileAvatarPath: '',
        profileNicknameRejected: false,
      })
      wx.showToast({ title: '资料已保存', icon: 'success' })
    } catch (e) {
      if (!this._alive || saveSeq !== this._profileSaveSeq) return
      const message = e && e.message ? e.message : '保存失败，请稍后重试'
      wx.showToast({ title: message, icon: 'none' })
    } finally {
      if (this._alive && saveSeq === this._profileSaveSeq) {
        this.setData({ profileSaving: false })
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
      const [dashRes, growthRes] = await Promise.all([
        api.get('/stats/dashboard'),
        api.get('/stats/growth').catch(() => null),
      ])
      if (
        !this._alive ||
        !this._visible ||
        requestSeq !== this._growthSeq ||
        showSeq !== this._showSeq
      ) return

      const overview = (dashRes && dashRes.overview) || {}
      const growth = growthRes || null
      this._lastGrowth = growth
      const snapshot = this.buildGrowthSnapshot(overview, growth)
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
      expText: levelMeta.expText,
      nextLevelText: levelMeta.nextLevelText,
      dailyBoostText: this.getDailyBoostText(0, todayGoalTotal, 0),
      badgeList: this.getBadgeList(0, 0, 0),
      badgeTitle: '今日待点亮',
      missionText: '完成一组练习，点亮今日目标',
    }
  },

  buildGrowthSnapshot(overview, growth) {
    this._lastOverview = overview || {}
    const streakDays = this.toNonNegativeInt(overview.consecutive_days)
    const todayGoalDone = this.toNonNegativeInt(overview.today_questions)
    const totalQuestions = this.toNonNegativeInt(overview.total_questions)
    const dueReviewCount = this.toNonNegativeInt(overview.due_review_count)
    const todayGoalTotal = this.getStoredTodayGoal()
    const levelProgress = Math.min(100, Math.round((todayGoalDone / todayGoalTotal) * 100))
    const taskSnapshot = this.getPrimaryTaskSnapshot(todayGoalDone, todayGoalTotal, dueReviewCount)

    this._growthTargets = { streakDays, todayGoalDone, levelProgress }

    if (growth) {
      const topBadges = (growth.badges || []).slice(0, 3)
      return {
        studyLevel: growth.level_title || 'Lv1 起步',
        levelProgress,
        todayGoalTotal,
        ...taskSnapshot,
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
      expText: levelMeta.expText,
      nextLevelText: levelMeta.nextLevelText,
      dailyBoostText: this.getDailyBoostText(todayGoalDone, todayGoalTotal, streakDays),
      badgeList: this.getBadgeList(streakDays, totalQuestions, levelProgress),
      badgeTitle: this.getBadgeTitle(streakDays, levelProgress),
      missionText: this.getMissionText(todayGoalDone, todayGoalTotal, dueReviewCount),
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
        primaryTaskTitle: `先复习 ${dueReviewCount} 道到期错题`,
        primaryTaskDesc: '这些题已进入复习窗口。先巩固记忆，再开始新练习，效率会更高。',
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
        primaryTaskTitle: `完成剩余 ${remainingCount} 道今日练习`,
        primaryTaskDesc: `今天已完成 ${todayGoalDone} 道。保持稳定节奏即可，不必一次全部做完。`,
        primaryTaskAction: '开始今日练习',
        secondaryTaskAction: '查看复习计划',
      }
    }

    return {
      dueReviewCount,
      remainingCount,
      primaryTaskType: 'complete',
      primaryTaskKicker: 'TODAY COMPLETE · 今日已完成',
      primaryTaskTitle: '今天的核心任务已完成',
      primaryTaskDesc: '节奏已经守住。可以用少量新题保持手感，也可以安心结束今天的学习。',
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
      ...this.buildGrowthSnapshot(this._lastOverview || {}, this._lastGrowth),
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
    if (this.data.primaryTaskType === 'review') {
      this.goReview()
      return
    }
    this.startRandom()
  },

  startSecondaryTask() {
    if (this.data.primaryTaskType === 'review') {
      this.startRandom()
      return
    }
    this.goReview()
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
    if (this._profilePromptTimer) {
      clearTimeout(this._profilePromptTimer)
      this._profilePromptTimer = null
      // It was scheduled but never displayed. Allow scheduling again on return.
      this._profilePrompted = false
    }
  },

  onUnload() {
    this._alive = false
    this._visible = false
    this._showSeq++
    this._growthSeq++
    this._profileSaveSeq++
    this._clearAnimTimer()
    clearTimeout(this._profilePromptTimer)
    this._profilePromptTimer = null
    clearTimeout(this._profileAutoSaveTimer)
    this._profileAutoSaveTimer = null
  },
})

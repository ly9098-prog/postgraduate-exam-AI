const api = require('../../../utils/api')
const storage = require('../../../utils/storage')
const growthAnimation = require('./growth-animation')
const growthClient = require('./growth-client')
const growthSnapshot = require('./growth-snapshot')
const auth = require('../../../utils/auth')
const loginGate = require('../../../utils/login-gate')
const { createLoginResume } = require('../../../utils/launch-resume')
const { userId } = require('../../../utils/launch-session-store')
const { getChinaWallParts } = require('../../../utils/china-time')

const { studyStrategy } = storage
const TODAY_GOAL_TOTAL = 30
const TODAY_GOAL_KEY = 'home_today_goal_total'
const GOAL_OPTIONS = [10, 20, 30, 50]

const growthPageMethods = {
  async _validateHomeSession() {
    const valid = auth.isLoggedIn() && await auth.checkAndRefreshToken()
    this._authed = Boolean(valid && auth.isLoggedIn())
    const owner = this._authed ? userId() : ''
    if (this._authed && this._homeOwner === owner) return
    this._homeOwner = owner
    this._growthSeq += 1
    this._clearAnimTimer()
    this._hasGrowthSnapshot = false
    this._lastDashboardSubjectStats = []
    this._lastOverview = {}
    this._lastGrowth = this._lastHub = this._lastPlan = null
    this._growthTargets = { streakDays: 0, todayGoalDone: 0, levelProgress: 0 }
  },

  _requireLogin(content) {
    if (this._authed) return true
    loginGate.promptLogin({
      content: content || '该功能会保存你的学习记录。可以先浏览体验，需要时再登录。',
    })
    return false
  },

  openLoginFromHome() {
    loginGate.openLogin()
  },

  startGuestTrial() {
    wx.navigateTo({ url: '/subpackages/study/practice/practice?guest=1' })
  },

  _guestBasePatch() {
    return {
      guestMode: true,
      user: {},
      studyLevel: '游客',
      subjectMastery: [],
      showGoalPicker: false,
      displayName: '同学',
      userInitial: '研',
      primaryTaskKicker: 'GUEST PREVIEW',
      primaryTaskTitle: '先体验随机练习',
      primaryTaskDesc: '可完成整组练习并查看答案解析，体验结果仅保存在本机。',
      primaryTaskAction: '开始体验',
      secondaryTaskAction: '学习报告',
      missionText: '顺序、推荐与个人记录登录后解锁',
    }
  },

  async _maybeResumeColdLaunch() {
    if (this._resumeAttempted) return
    this._resumeAttempted = true
    const resume = createLoginResume()
    const owner = userId()
    try {
      if (!await auth.checkAndRefreshToken()) return
      const target = await resume.resolve()
      if (!auth.isLoggedIn() || owner !== userId()) return
      if (!target || target === '/pages/home/home') {
        resume.complete()
        return
      }
      if (!this._alive || !this._visible) return
      wx.reLaunch({ url: target, success: () => resume.complete() })
    } catch (_) {
      if (auth.isLoggedIn() && owner === userId()) resume.complete()
    } finally {
      this._resumeAttempted = false
    }
  },

  getDisplayName(user) {
    const name = user && (user.nickName || user.nickname || user.name)
    return name ? String(name).trim().slice(0, 8) : '研友'
  },

  getUserInitial(user) {
    const name = this.getDisplayName(user)
    return name ? name.slice(0, 1) : '研'
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
  async loadGrowthSnapshot(showSeq = this._showSeq) {
    if (!this._alive || !this._visible) return
    const requestSeq = ++this._growthSeq
    this._clearAnimTimer()
    try {
      const growthResponses = await this._fetchGrowthResponses()
      if (this._isGrowthStale(requestSeq, showSeq)) return
      this._applyGrowthResponses(growthResponses, requestSeq)
    } catch (error) {
      if (this._isGrowthStale(requestSeq, showSeq)) return
      console.error('加载成长数据失败', error)
    }
  },

  _fetchGrowthResponses() {
    return growthClient.fetchGrowthResponses(this._growthApi || api)
  },

  _isGrowthStale(requestSeq, showSeq) {
    return growthClient.isGrowthStale({
      alive: this._alive,
      visible: this._visible,
      requestSeq,
      showSeq,
      growthSeq: this._growthSeq,
      currentShowSeq: this._showSeq,
    })
  },

  _applyGrowthResponses(responses, requestSeq) {
    const dashboard = responses.dashboard || {}
    const overview = dashboard.overview || {}
    const dashboardSubjectStats = Array.isArray(dashboard.subject_stats)
      ? dashboard.subject_stats
      : []
    const snapshot = this.buildGrowthSnapshot({
      overview,
      growth: responses.growth || null,
      hub: responses.hub,
      plan: responses.plan,
      dashboardSubjectStats,
    })
    this._hasGrowthSnapshot = true
    this.setData(snapshot, () => {
      if (this._alive && this._visible && requestSeq === this._growthSeq) {
        this._animateNumbers()
      }
    })
  },

  _animateNumbers() {
    growthAnimation.start(this)
  },

  _animateNumbersTick(from, to, durations, startTime) {
    growthAnimation.tick(this, { from, to, durations, startTime })
  },

  _clearAnimTimer() {
    growthAnimation.clear(this)
  },

  getGrowthFallback() {
    return growthSnapshot.getGrowthFallback({
      todayGoalTotal: this.getStoredTodayGoal(),
    })
  },

  buildGrowthSnapshot(options = {}) {
    const opts = options || {}
    this._lastOverview = opts.overview || {}
    this._lastGrowth = opts.growth || null
    this._lastHub = opts.hub || null
    this._lastPlan = opts.plan || null
    if (Array.isArray(opts.dashboardSubjectStats)) {
      this._lastDashboardSubjectStats = opts.dashboardSubjectStats
    }
    const result = growthSnapshot.buildGrowthSnapshot({
      ...opts,
      todayGoalTotal: this.getStoredTodayGoal(),
      lastDashboardSubjectStats: this._lastDashboardSubjectStats,
      studyStrategy,
    })
    this._growthTargets = result.targets
    return result.snapshot
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
      ...this.buildGrowthSnapshot({
        overview: this._lastOverview || {},
        growth: this._lastGrowth,
        hub: this._lastHub,
        plan: this._lastPlan,
      }),
      showGoalPicker: false,
    })
    this._animateNumbers()
  },
}

module.exports = {
  GOAL_OPTIONS,
  TODAY_GOAL_TOTAL,
  growthPageMethods,
}

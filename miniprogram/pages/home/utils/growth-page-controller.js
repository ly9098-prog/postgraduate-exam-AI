const api = require('../../../utils/api')
const storage = require('../../../utils/storage')
const growthAnimation = require('./growth-animation')
const growthClient = require('./growth-client')
const growthSnapshot = require('./growth-snapshot')

const { studyStrategy } = storage
const TODAY_GOAL_TOTAL = 30
const TODAY_GOAL_KEY = 'home_today_goal_total'
const GOAL_OPTIONS = [10, 20, 30, 50]

const growthPageMethods = {
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

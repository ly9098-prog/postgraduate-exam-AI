const auth = require('../../utils/auth')
const api = require('../../utils/api')
const storage = require('../../utils/storage')

const TODAY_GOAL_TOTAL = 30
const TODAY_GOAL_KEY = 'home_today_goal_total'
const GOAL_OPTIONS = [10, 20, 30, 50]

Page({
  data: {
    user: {},
    greeting: '',
    dateStr: '',
    motto: '',
    isAdmin: false,
    _animStreakDays: 0,
    studyLevel: 'Lv1 起步',
    _animLevelProgress: 0,
    _animGoalDone: 0,
    todayGoalTotal: TODAY_GOAL_TOTAL,
    goalOptions: GOAL_OPTIONS,
    showGoalPicker: false,
    expText: '0 / 50 EXP',
    nextLevelText: '距离 Lv2 还差 50 题',
    dailyBoostText: '完成今日目标后，可点亮坚持徽章',
    badgeList: [],
    badgeTitle: '今日待点亮',
    missionText: '完成一组练习，点亮今日目标',
  },
  _growthTargets: { streakDays: 0, todayGoalDone: 0, levelProgress: 0 },

  async onShow() {
    this._authed = auth.isLoggedIn()
    this.setData({
      user: auth.getUser() || {},
      isAdmin: this._authed ? auth.isAdmin() : false,
      greeting: this.getGreeting(),
      dateStr: this.getDateStr(),
      motto: this.getMotto(),
      ...this.getGrowthFallback(),
    })
    if (!this._authed) return
    try {
      const syncedUser = await auth.syncCurrentUser()
      if (!syncedUser) return
      this.setData({ user: syncedUser || {}, isAdmin: auth.isAdmin() })
    } catch (e) {
      console.error('同步用户权限失败', e)
      return
    }
    await this.loadGrowthSnapshot()
  },

  async loadGrowthSnapshot() {
    this._clearAnimTimers()
    this._animSeq = (this._animSeq || 0) + 1
    const seq = this._animSeq
    this.setData({ _animStreakDays: 0, _animGoalDone: 0, _animLevelProgress: 0 })
    try {
      const [dashRes, growthRes] = await Promise.all([
        api.get('/stats/dashboard'),
        api.get('/stats/growth').catch(() => null),
      ])
      if (seq !== this._animSeq) return
      const overview = (dashRes && dashRes.overview) || {}
      const growth = growthRes || null
      this._lastGrowth = growth
      const snapshot = this.buildGrowthSnapshot(overview, growth)
      this._growthTargets.streakDays = snapshot.streakDays
      this._growthTargets.todayGoalDone = snapshot.todayGoalDone
      this._growthTargets.levelProgress = snapshot.levelProgress
      const { streakDays, todayGoalDone, levelProgress, ...displayData } = snapshot
      this.setData(displayData)
      this._animateGrowth()
    } catch (e) {
      console.error('加载成长数据失败', e)
    }
  },

  // 统一动画调度：一次计算三个字段，合并为一次 setData，间隔 100ms
  _animateGrowth() {
    this._clearAnimTimers()
    const { streakDays, todayGoalDone, levelProgress } = this._growthTargets
    const from = { sd: this.data._animStreakDays, gd: this.data._animGoalDone, lp: this.data._animLevelProgress }
    const to = { sd: streakDays, gd: todayGoalDone, lp: levelProgress }
    if (from.sd === to.sd && from.gd === to.gd && from.lp === to.lp) return
    const durationMap = { sd: 600, gd: 600, lp: 500 }
    const defaults = { sd: 0, gd: 0, lp: 0 }
    const startTime = Date.now()
    // 最大动画时长取各字段最大值
    const maxDur = Math.max(...Object.keys(durationMap).map(k => durationMap[k]))
    const tick = () => {
      if (this._animSeq !== this._lastAnimSeq) return
      const elapsed = Date.now() - startTime
      const p = Math.min(elapsed / maxDur, 1)
      const eased = 1 - Math.pow(1 - p, 3)
      const update = {}
      ;['sd', 'gd', 'lp'].forEach(key => {
        const dur = durationMap[key]
        const localP = Math.min(elapsed / dur, 1)
        const localEased = 1 - Math.pow(1 - localP, 3)
        const fr = from[key]
        const t = to[key]
        const diff = t - fr
        const current = Math.round(fr + diff * localEased)
        const clamped = Math.min(t, Math.max(Math.min(fr, t), current))
        const dataMap = { sd: '_animStreakDays', gd: '_animGoalDone', lp: '_animLevelProgress' }
        update[dataMap[key]] = clamped
      })
      this.setData(update)
      if (p < 1) {
        this._animTimer = setTimeout(tick, 100)
      }
    }
    this._lastAnimSeq = this._animSeq
    tick()
  },

  getGrowthFallback() {
    const todayGoalTotal = this.getStoredTodayGoal()
    const levelMeta = this.getLevelMeta(0)
    this._growthTargets = { streakDays: 0, todayGoalDone: 0, levelProgress: 0 }
    return {
      studyLevel: 'Lv1 起步',
      todayGoalTotal,
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

    if (growth) {
      const topBadges = (growth.badges || []).slice(0, 3)
      return {
        streakDays,
        studyLevel: growth.level_title || 'Lv1 起步',
        levelProgress,
        todayGoalDone,
        todayGoalTotal,
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
      streakDays,
      studyLevel: levelMeta.studyLevel,
      levelProgress,
      todayGoalDone,
      todayGoalTotal,
      expText: levelMeta.expText,
      nextLevelText: levelMeta.nextLevelText,
      dailyBoostText: this.getDailyBoostText(todayGoalDone, todayGoalTotal, streakDays),
      badgeList: this.getBadgeList(streakDays, totalQuestions, levelProgress),
      badgeTitle: this.getBadgeTitle(streakDays, levelProgress),
      missionText: this.getMissionText(todayGoalDone, todayGoalTotal, dueReviewCount),
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
    const snapshot = this.buildGrowthSnapshot(this._lastOverview || {}, this._lastGrowth)
    this._growthTargets.streakDays = snapshot.streakDays
    this._growthTargets.todayGoalDone = snapshot.todayGoalDone
    this._growthTargets.levelProgress = snapshot.levelProgress
    const { streakDays, todayGoalDone, levelProgress, ...displayData } = snapshot
    this.setData({
      _animStreakDays: 0,
      _animGoalDone: 0,
      _animLevelProgress: 0,
      ...displayData,
      showGoalPicker: false,
    })
    this._animateGrowth()
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
    if (remaining === 0) return '今日目标已达成，明天打开可延续学习连续感'
    if (streakDays >= 7) return `连续学习 ${streakDays} 天，再完成 ${remaining} 题守住节奏`
    return `再坚持 ${remaining} 题，给今天的学习打上完成标记`
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
      if (dueReviewCount > 0) return `今日目标完成，再复习 ${dueReviewCount} 题巩固记忆`
      return '今日目标已完成，保持节奏'
    }
    if (dueReviewCount > 0) {
      return `再完成 ${remaining} 题，另有 ${dueReviewCount} 道复习待处理`
    }
    return `再完成 ${remaining} 题，点亮今日目标`
  },

  toNonNegativeInt(value) {
    const n = Number(value)
    if (!Number.isFinite(n) || n < 0) return 0
    return Math.round(n)
  },

  getGreeting() {
    const h = new Date().getHours()
    if (h < 6) return '夜深了'
    if (h < 9) return '早上好'
    if (h < 12) return '上午好'
    if (h < 14) return '中午好'
    if (h < 18) return '下午好'
    return '晚上好'
  },

  getMotto() {
    const h = new Date().getHours()
    if (h < 6) return '休息也是学习的一部分，明天再战'
    if (h < 9) return '清晨是记忆的黄金时间'
    if (h < 12) return '开始今天的学习计划吧'
    if (h < 14) return '午后小憩一下，学习更高效'
    if (h < 18) return '保持专注，坚持就是胜利'
    return '完成今日计划，收获满满成就感'
  },

  getDateStr() {
    const d = new Date()
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.getMonth()+1}月${d.getDate()}日 · 星期${week[d.getDay()]}`
  },

  startRandom() { wx.navigateTo({ url: '/pages/practice/practice' }) },
  goWrongBook() { wx.navigateTo({ url: '/pages/wrong-book/wrong-book' }) },
  goReview() { wx.navigateTo({ url: '/pages/review-today/review-today' }) },
  goDashboard() { wx.navigateTo({ url: '/pages/dashboard/dashboard' }) },
  goPomodoro() { wx.navigateTo({ url: '/pages/pomodoro/pomodoro' }) },
  _clearAnimTimers() {
    this._animSeq = (this._animSeq || 0) + 1
    if (this._animTimer) {
      clearTimeout(this._animTimer)
      this._animTimer = null
    }
  },

  onHide() {
    this._clearAnimTimers()
  },

  onUnload() {
    this._clearAnimTimers()
  },
})

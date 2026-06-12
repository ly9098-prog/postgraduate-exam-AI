const auth = require('../../utils/auth')
const api = require('../../utils/api')

const TODAY_GOAL_TOTAL = 30

Page({
  data: {
    user: {},
    greeting: '',
    dateStr: '',
    motto: '',
    authed: false,
    isAdmin: false,
    streakDays: 0,
    studyLevel: 'Lv1 起步',
    levelProgress: 0,
    todayGoalDone: 0,
    todayGoalTotal: TODAY_GOAL_TOTAL,
    badgeTitle: '今日待点亮',
    missionText: '完成一组练习，点亮今日目标',
  },

  async onShow() {
    const authed = auth.isLoggedIn()
    this.setData({
      user: auth.getUser() || {},
      authed,
      isAdmin: authed ? auth.isAdmin() : false,
      greeting: this.getGreeting(),
      dateStr: this.getDateStr(),
      motto: this.getMotto(),
      ...this.getGrowthFallback(),
    })
    if (!authed) return
    try {
      const syncedUser = await auth.syncCurrentUser()
      this.setData({ user: syncedUser || {}, isAdmin: auth.isAdmin() })
    } catch (e) {
      console.error('同步用户权限失败', e)
    }
    await this.loadGrowthSnapshot()
  },

  async loadGrowthSnapshot() {
    try {
      const res = await api.get('/stats/dashboard')
      this.setData(this.buildGrowthSnapshot((res && res.overview) || {}))
    } catch (e) {
      console.error('加载成长数据失败', e)
    }
  },

  getGrowthFallback() {
    return {
      streakDays: 0,
      studyLevel: 'Lv1 起步',
      levelProgress: 0,
      todayGoalDone: 0,
      todayGoalTotal: TODAY_GOAL_TOTAL,
      badgeTitle: '今日待点亮',
      missionText: '完成一组练习，点亮今日目标',
    }
  },

  buildGrowthSnapshot(overview) {
    const streakDays = this.toNonNegativeInt(overview.consecutive_days)
    const todayGoalDone = this.toNonNegativeInt(overview.today_questions)
    const totalQuestions = this.toNonNegativeInt(overview.total_questions)
    const dueReviewCount = this.toNonNegativeInt(overview.due_review_count)
    const todayGoalTotal = TODAY_GOAL_TOTAL
    const levelProgress = Math.min(100, Math.round((todayGoalDone / todayGoalTotal) * 100))

    return {
      streakDays,
      studyLevel: this.getStudyLevel(totalQuestions),
      levelProgress,
      todayGoalDone,
      todayGoalTotal,
      badgeTitle: this.getBadgeTitle(streakDays, levelProgress),
      missionText: this.getMissionText(todayGoalDone, todayGoalTotal, dueReviewCount),
    }
  },

  getStudyLevel(totalQuestions) {
    if (totalQuestions >= 1000) return 'Lv5 上岸冲刺'
    if (totalQuestions >= 500) return 'Lv4 高效进阶'
    if (totalQuestions >= 200) return 'Lv3 刷题达人'
    if (totalQuestions >= 50) return 'Lv2 坚持者'
    return 'Lv1 起步'
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
  goImport() {
    wx.navigateTo({ url: '/pages/import/import' })
  },
})

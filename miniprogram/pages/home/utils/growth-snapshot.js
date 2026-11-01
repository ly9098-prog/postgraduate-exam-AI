const { toNonNegativeInt } = require('./growth-mastery')
const growthView = require('./growth-view')

function buildGrowthContext(options = {}) {
  const overview = options.overview || {}
  const hub = options.hub || null
  const plan = options.plan || null
  const effectiveSubjectStats = Array.isArray(options.dashboardSubjectStats)
    ? options.dashboardSubjectStats
    : (Array.isArray(options.lastDashboardSubjectStats) ? options.lastDashboardSubjectStats : [])
  const streakDays = toNonNegativeInt(overview.consecutive_days)
  const hubTodayQuestions = hub && hub.scope_ready !== false ? hub.today_question_count : null
  const todayGoalDone = toNonNegativeInt(
    hubTodayQuestions != null ? hubTodayQuestions : overview.today_questions,
  )
  const totalQuestions = toNonNegativeInt(overview.total_questions)
  const hubReviewRemaining = hub && hub.review ? hub.review.remaining_count : null
  const dueReviewCount = toNonNegativeInt(
    hubReviewRemaining != null ? hubReviewRemaining : overview.due_review_count,
  )
  const todayGoalTotal = options.todayGoalTotal
  const levelProgress = Math.min(100, Math.round((todayGoalDone / todayGoalTotal) * 100))
  const hubDisplay = growthView.getHubDisplaySnapshot({
    hub,
    dashboardSubjectStats: effectiveSubjectStats,
  })
  const planDisplay = growthView.getStudyPlanDisplaySnapshot(plan)
  const taskSnapshot = hubDisplay.studyHubAvailable
    ? growthView.getHubPrimaryTaskSnapshot({ hub, todayGoalDone, todayGoalTotal })
    : growthView.getPrimaryTaskSnapshot({ todayGoalDone, todayGoalTotal, dueReviewCount })
  const strategySnapshot = growthView.getStrategyPrimaryTaskSnapshot({
    studyStrategy: options.studyStrategy,
    hub,
    dueReviewCount,
    todayGoalDone,
    todayGoalTotal,
    subjectMastery: hubDisplay.subjectMastery || [],
  })
  return {
    streakDays,
    todayGoalDone,
    totalQuestions,
    dueReviewCount,
    todayGoalTotal,
    levelProgress,
    hubDisplay,
    planDisplay,
    taskSnapshot,
    strategySnapshot,
  }
}

function buildGrowthWithBadges(ctx, growth) {
  const { todayGoalDone, todayGoalTotal, levelProgress, streakDays, dueReviewCount } = ctx
  const { hubDisplay, planDisplay, strategySnapshot, taskSnapshot } = ctx
  const topBadges = (growth.badges || []).slice(0, 3)
  return {
    studyLevel: growth.level_title || 'Lv1 起步',
    levelProgress,
    todayGoalTotal,
    ...(strategySnapshot || taskSnapshot),
    ...hubDisplay,
    ...planDisplay,
    expText: `${growth.exp_current || 0} / ${growth.exp_to_next || 0} EXP`,
    nextLevelText: growth.level_progress_pct >= 100
      ? '已满级，继续保持题感'
      : `距离下一级还差 ${Math.max(0, (growth.exp_to_next || 0) - (growth.exp_current || 0))} EXP`,
    dailyBoostText: growth.daily_boost || growthView.getDailyBoostText({
      todayGoalDone,
      todayGoalTotal,
      streakDays,
    }),
    badgeList: topBadges.map(badge => ({
      key: badge.key,
      title: badge.title,
      desc: badge.unlocked ? '已点亮' : badge.desc,
      unlocked: badge.unlocked,
    })),
    badgeTitle: streakDays >= 30
      ? '连续30天徽章'
      : streakDays >= 7
        ? '连续7天徽章'
        : topBadges.some(badge => badge.unlocked) ? '徽章进行中' : '今日待点亮',
    missionText: growthView.getMissionText({
      todayGoalDone,
      todayGoalTotal,
      dueReviewCount,
    }),
  }
}

function buildGrowthWithoutBadges(ctx) {
  const {
    streakDays,
    todayGoalDone,
    totalQuestions,
    levelProgress,
    todayGoalTotal,
    dueReviewCount,
  } = ctx
  const { hubDisplay, planDisplay, strategySnapshot, taskSnapshot } = ctx
  const levelMeta = growthView.getLevelMeta(totalQuestions)
  return {
    studyLevel: levelMeta.studyLevel,
    levelProgress,
    todayGoalTotal,
    ...(strategySnapshot || taskSnapshot),
    ...hubDisplay,
    ...planDisplay,
    expText: levelMeta.expText,
    nextLevelText: levelMeta.nextLevelText,
    dailyBoostText: growthView.getDailyBoostText({
      todayGoalDone,
      todayGoalTotal,
      streakDays,
    }),
    badgeList: growthView.getBadgeList({ streakDays, totalQuestions, levelProgress }),
    badgeTitle: growthView.getBadgeTitle({ streakDays, levelProgress }),
    missionText: growthView.getMissionText({
      todayGoalDone,
      todayGoalTotal,
      dueReviewCount,
    }),
  }
}

function buildGrowthSnapshot(options = {}) {
  const ctx = buildGrowthContext(options)
  return {
    snapshot: options.growth
      ? buildGrowthWithBadges(ctx, options.growth)
      : buildGrowthWithoutBadges(ctx),
    targets: {
      streakDays: ctx.streakDays,
      todayGoalDone: ctx.todayGoalDone,
      levelProgress: ctx.levelProgress,
    },
  }
}

function getGrowthFallback(options = {}) {
  const todayGoalTotal = options.todayGoalTotal
  const levelMeta = growthView.getLevelMeta(0)
  return {
    studyLevel: 'Lv1 起步',
    levelProgress: 0,
    todayGoalTotal,
    ...growthView.getPrimaryTaskSnapshot({
      todayGoalDone: 0,
      todayGoalTotal,
      dueReviewCount: 0,
    }),
    ...growthView.getHubDisplaySnapshot({ hub: null, dashboardSubjectStats: [] }),
    ...growthView.getStudyPlanDisplaySnapshot(null),
    expText: levelMeta.expText,
    nextLevelText: levelMeta.nextLevelText,
    dailyBoostText: growthView.getDailyBoostText({
      todayGoalDone: 0,
      todayGoalTotal,
      streakDays: 0,
    }),
    badgeList: growthView.getBadgeList({
      streakDays: 0,
      totalQuestions: 0,
      levelProgress: 0,
    }),
    badgeTitle: '今日待点亮',
    missionText: '完成一组练习，点亮今日目标',
  }
}

module.exports = {
  buildGrowthContext,
  buildGrowthSnapshot,
  getGrowthFallback,
}

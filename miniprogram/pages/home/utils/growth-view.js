const { buildSubjectMastery, toNonNegativeInt } = require('./growth-mastery')

function getStudyPlanDisplaySnapshot(plan) {
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
    planDaysRemaining: toNonNegativeInt(countdown.days_remaining),
    planPhaseLabel: String(countdown.phase_label || ''),
    planTargetDateText: targetDate,
    planTodayText: today.is_rest_day
      ? '本周目标已达成，今天建议轻量复盘'
      : `今日 ${toNonNegativeInt(today.completed_minutes)} / ${toNonNegativeInt(today.target_minutes)} 分钟`,
    planWeeklyText: `本周 ${toNonNegativeInt(weekly.active_days)} / ${toNonNegativeInt(weekly.target_days)} 天`,
    planProgressPercent: Math.max(0, Math.min(100, toNonNegativeInt(today.completion_percent))),
    planPrimaryText: primary && primary.title
      ? String(primary.title)
      : '今天的计划已完成或暂无强制任务',
  }
}

function buildHubTaskDisplay(task) {
  const taskTypeMeta = {
    review: { eyebrow: '记忆优先', iconSrc: '/assets/icons/home-actions/refresh-cw.svg' },
    weakness: { eyebrow: '弱项强化', iconSrc: '/assets/icons/home-actions/target.svg' },
    hard_questions: { eyebrow: '困难题重练', iconSrc: '/assets/icons/home-actions/triangle-alert.svg' },
    knowledge_path: { eyebrow: '知识路径', iconSrc: '/assets/icons/home-actions/route.svg' },
    knowledge_chapter: { eyebrow: '章节专项', iconSrc: '/assets/icons/home-actions/book-open-check.svg' },
    smart_practice: { eyebrow: '智能新题', iconSrc: '/assets/icons/home-actions/sparkles.svg' },
  }
  const meta = taskTypeMeta[task.task_type] || {
    eyebrow: '今日任务',
    iconSrc: '/assets/icons/home-actions/target.svg',
  }
  const q = toNonNegativeInt(task.estimated_question_count)
  const m = toNonNegativeInt(task.estimated_minutes)
  return {
    key: task.key,
    taskType: task.task_type,
    eyebrow: meta.eyebrow,
    iconSrc: meta.iconSrc,
    title: task.title || '继续学习',
    reason: task.reason || '',
    actionLabel: task.action_label || '开始',
    metaText: task.completed_today
      ? `今日已完成 · ${q > 0 ? '约 ' + q + ' 题' : '可再次练习'}`
      : (q > 0 ? `约 ${q} 题 · ${m || 1} 分钟` : '按当前学习状态推荐'),
    completedToday: Boolean(task.completed_today),
    route: task.route || '',
    routeParams: task.route_params || {},
  }
}

function getHubDisplaySnapshot(options = {}) {
  const hub = options.hub
  const dashboardSubjectStats = options.dashboardSubjectStats
  const subjectMastery = buildSubjectMastery({
    hubSubjectMastery: hub && Array.isArray(hub.subject_mastery) ? hub.subject_mastery : [],
    dashboardSubjectStats,
  })
  const available = !!(hub && hub.scope_ready !== false && hub.primary_task)
  if (!available) {
    return {
      studyHubAvailable: false,
      studyHubFallback: false,
      hubPrimaryTask: null,
      hubSecondaryTask: null,
      hubTasks: [],
      hubRecommendationCount: 0,
      hubCompletedRecommendationCount: 0,
      subjectMastery,
    }
  }
  const allTasks = Array.isArray(hub.tasks) ? hub.tasks : []
  const primaryKey = hub.primary_task && hub.primary_task.key
  const secondaryRaw = allTasks.find(task => task && task.key !== primaryKey) || null
  // The focus card plus these two cards are the complete recommendation surface.
  const displayTasks = allTasks
    .filter(task => task && task.key !== primaryKey)
    .slice(0, 2)
    .map(task => buildHubTaskDisplay(task))
  const completedRecommendationCount = Math.min(
    3,
    toNonNegativeInt(hub.completed_recommendation_count),
  )
  return {
    studyHubAvailable: true,
    studyHubFallback: !!hub.fallback_used,
    hubPrimaryTask: hub.primary_task,
    hubSecondaryTask: secondaryRaw,
    hubTasks: displayTasks,
    hubRecommendationCount: Math.min(
      3,
      toNonNegativeInt(hub.recommended_task_count) || (1 + displayTasks.length),
    ),
    hubCompletedRecommendationCount: completedRecommendationCount,
    subjectMastery,
  }
}

function getPrimaryTaskSnapshot(options = {}) {
  const todayGoalDone = options.todayGoalDone || 0
  const todayGoalTotal = options.todayGoalTotal || 0
  const dueReviewCount = options.dueReviewCount || 0
  const remainingCount = Math.max(0, todayGoalTotal - todayGoalDone)
  if (dueReviewCount > 0) {
    return {
      dueReviewCount,
      remainingCount,
      primaryTaskType: 'review',
      primaryTaskKicker: 'MEMORY FIRST · 今日优先',
      primaryTaskTitle: `先复习 ${dueReviewCount} 道到期错题`,
      primaryTaskDesc: '这些错题已进入复习窗口。先巩固记忆，再开始新练习，效率会更高。',
      primaryTaskAction: '开始今日复习',
      secondaryTaskAction: '先做新题',
    }
  }
  if (remainingCount > 0) {
    return {
      dueReviewCount,
      remainingCount,
      primaryTaskType: 'practice',
      primaryTaskKicker: 'TODAY PLAN · 今日目标',
      primaryTaskTitle: `完成剩余 ${remainingCount} 道练习`,
      primaryTaskDesc: `今天已完成 ${todayGoalDone} 道练习。保持稳定节奏即可，不必一次全部做完。`,
      primaryTaskAction: '开始练习',
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
}

function getHubPrimaryTaskSnapshot(options = {}) {
  const hub = options.hub
  const task = hub && hub.primary_task ? hub.primary_task : null
  if (!task) {
    return getPrimaryTaskSnapshot({
      todayGoalDone: options.todayGoalDone,
      todayGoalTotal: options.todayGoalTotal,
      dueReviewCount: 0,
    })
  }
  const dueReviewCount = toNonNegativeInt(hub && hub.review && hub.review.remaining_count)
  return {
    dueReviewCount,
    remainingCount: Math.max(0, options.todayGoalTotal - options.todayGoalDone),
    primaryTaskType: task.task_type || 'practice',
    primaryTaskKicker: task.completed_today
      ? 'SMART STUDY · 今日已完成'
      : 'SMART STUDY · 今日优先',
    primaryTaskTitle: task.title || '继续今日学习',
    primaryTaskDesc: task.reason || '根据当前学习状态安排下一项任务。',
    primaryTaskAction: task.completed_today ? '再练一次' : (task.action_label || '开始学习'),
    secondaryTaskAction: '查看学习报告',
  }
}

// Explicit strategy injection keeps this pure view layer independent of storage.
function getStrategyPrimaryTaskSnapshot(options = {}) {
  const studyStrategy = options.studyStrategy
  if (!studyStrategy || typeof studyStrategy.buildNextBestAction !== 'function') return null
  try {
    const task = studyStrategy.buildNextBestAction({
      dueReviewCount: options.dueReviewCount,
      hub: options.hub,
      subjectMastery: options.subjectMastery,
    })
    if (!task || !task.route) return null
    const fallback = getPrimaryTaskSnapshot({
      todayGoalDone: options.todayGoalDone || 0,
      todayGoalTotal: options.todayGoalTotal || 0,
      dueReviewCount: options.dueReviewCount || 0,
    })
    return {
      dueReviewCount: fallback.dueReviewCount,
      remainingCount: fallback.remainingCount,
      primaryTaskType: task.task_type || 'practice',
      primaryTaskKicker: 'STRATEGY · 今日优先',
      primaryTaskTitle: task.title || '继续今日学习',
      primaryTaskDesc: task.reason || '根据四科学习策略安排下一项任务。',
      primaryTaskAction: task.action_label || '开始学习',
      primaryTaskRoute: task.route,
      primaryTaskParams: task.route_params || {},
      secondaryTaskAction: '查看学习报告',
    }
  } catch (error) {
    console.warn('[HOME_STRATEGY_NBA] unavailable', error)
    return null
  }
}

function getLevelMeta(totalQuestions) {
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
}

function getDailyBoostText(options = {}) {
  const remaining = Math.max(0, (options.todayGoalTotal || 0) - (options.todayGoalDone || 0))
  if (remaining === 0) return '今日目标已经完成。稳定结束，比临时加量更有利于长期坚持。'
  if ((options.streakDays || 0) >= 7) {
    return `你已经连续学习 ${options.streakDays} 天。再完成 ${remaining} 题，就能守住今天的节奏。`
  }
  return `不需要追求一次做完；先完成一组，再决定是否继续。今天还剩 ${remaining} 题。`
}

function getBadgeList(options = {}) {
  return [
    { key: 'today', title: '今日目标', desc: '完成每日题量', unlocked: (options.levelProgress || 0) >= 100 },
    { key: 'streak7', title: '连续 7 天', desc: '保持复习节奏', unlocked: (options.streakDays || 0) >= 7 },
    { key: 'hundred', title: '百题积累', desc: '累计完成 100 题', unlocked: (options.totalQuestions || 0) >= 100 },
  ]
}

function getStudyLevel(totalQuestions) {
  return getLevelMeta(totalQuestions).studyLevel
}

function getBadgeTitle(options = {}) {
  const levelProgress = options.levelProgress || 0
  const streakDays = options.streakDays || 0
  if (levelProgress >= 100) return '今日目标已完成'
  if (streakDays >= 30) return '连续 30 天徽章'
  if (streakDays >= 15) return '连续 15 天徽章'
  if (streakDays >= 7) return '连续 7 天徽章'
  if (streakDays > 0) return '坚持学习徽章'
  return '今日待点亮'
}

function getMissionText(options = {}) {
  const remaining = Math.max(0, (options.todayGoalTotal || 0) - (options.todayGoalDone || 0))
  const dueReviewCount = options.dueReviewCount || 0
  if (remaining === 0) {
    if (dueReviewCount > 0) return `目标已完成，仍有 ${dueReviewCount} 道到期复习`
    return '今日目标已完成，保持节奏'
  }
  if (dueReviewCount > 0) return `先处理到期复习，再完成 ${remaining} 道新题`
  return `再完成 ${remaining} 题，点亮今日目标`
}

module.exports = {
  getStudyPlanDisplaySnapshot,
  getHubDisplaySnapshot,
  getHubPrimaryTaskSnapshot,
  getStrategyPrimaryTaskSnapshot,
  getPrimaryTaskSnapshot,
  getLevelMeta,
  getDailyBoostText,
  getBadgeList,
  getStudyLevel,
  getBadgeTitle,
  getMissionText,
}

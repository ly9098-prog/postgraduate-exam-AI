/**
 * Dashboard data model — formatting, view-model construction, insights.
 * Extracted from dashboard.js to keep page logic lean.
 */

const { getSubjectName } = require('./utils/subject-meta')

/** Subject palette (stable per index hash) */
const SUBJECT_COLORS = ['#4F7FFF', '#22C55E', '#F59E0B', '#EF4444', '#8B5CF6', '#06B6D4']

function subjectLabel(code) {
  return getSubjectName(code)
}

function fmtDuration(sec) {
  const s = Math.max(0, sec || 0)
  if (s < 60) return s + '秒'
  const m = Math.floor(s / 60)
  if (m < 60) return m + '分' + (s % 60 > 0 ? s % 60 + '秒' : '')
  const h = Math.floor(m / 60)
  return h + '时' + (m % 60 > 0 ? m % 60 + '分' : '')
}

function accuracyPct(v) {
  return Math.round((v || 0) * 100)
}

function accuracyClass(v) {
  const pct = accuracyPct(v)
  return pct >= 70 ? 'green' : pct >= 40 ? 'orange' : 'red'
}

/**
 * Build hero view-model from dashboard-v2 overview.
 */
function buildHero(ov) {
  if (!ov) return null
  return {
    todayQuestions: ov.today_questions || 0,
    todayCorrect: ov.today_correct || 0,
    todayAccuracy: accuracyPct(ov.today_accuracy),
    todayDurationText: fmtDuration(ov.today_duration_sec || 0),
    totalAccuracy: ov.accuracy || 0,
    totalAccuracyPct: accuracyPct(ov.accuracy),
    consecutiveDays: ov.consecutive_days || 0,
    dueReviewCount: ov.due_review_count || 0,
    totalQuestions: ov.total_questions || 0,
    totalCorrect: ov.total_correct || 0,
    totalWrong: ov.total_wrong || 0,
  }
}

/**
 * Build trends view-model.
 */
function buildTrends(tr) {
  if (!tr || !tr.points || !tr.points.length) return null

  const normalizePoint = p => ({
    date: p.date,
    shortDate: (p.date || '').slice(5),
    questions: p.questions || 0,
    correct: p.correct || 0,
    accuracy: p.accuracy || 0,
    accuracyPct: accuracyPct(p.accuracy),
    accuracyClass: accuracyClass(p.accuracy),
  })

  const points = tr.points.map(normalizePoint)
  const previousPoints = (tr.previous_points || []).map(normalizePoint)
  const totalQuestions = tr.total_questions != null
    ? tr.total_questions
    : points.reduce((sum, p) => sum + p.questions, 0)
  const activeDays = tr.active_days != null
    ? tr.active_days
    : points.filter(p => p.questions > 0).length
  const avgAccuracy = tr.avg_accuracy != null
    ? tr.avg_accuracy
    : (() => {
        const q = points.reduce((sum, p) => sum + p.questions, 0)
        const c = points.reduce((sum, p) => sum + p.correct, 0)
        return q > 0 ? c / q : 0
      })()
  const avgPct = accuracyPct(avgAccuracy)

  const previousTotalQuestions = tr.previous_total_questions != null
    ? tr.previous_total_questions
    : previousPoints.reduce((sum, p) => sum + p.questions, 0)
  const previousActiveDays = tr.previous_active_days != null
    ? tr.previous_active_days
    : previousPoints.filter(p => p.questions > 0).length
  const previousAvgAccuracy = tr.previous_avg_accuracy != null
    ? tr.previous_avg_accuracy
    : (() => {
        const q = previousPoints.reduce((sum, p) => sum + p.questions, 0)
        const c = previousPoints.reduce((sum, p) => sum + p.correct, 0)
        return q > 0 ? c / q : 0
      })()
  const previousAvgPct = accuracyPct(previousAvgAccuracy)
  const hasPrevious = previousPoints.length > 0

  const accuracyDelta = avgPct - previousAvgPct
  let accuracyCompareText = '等待上周期数据'
  let accuracyCompareClass = 'neutral'
  if (hasPrevious) {
    if (accuracyDelta > 0) {
      accuracyCompareText = `较上周期 +${accuracyDelta} 个百分点`
      accuracyCompareClass = 'up'
    } else if (accuracyDelta < 0) {
      accuracyCompareText = `较上周期 ${accuracyDelta} 个百分点`
      accuracyCompareClass = 'down'
    } else {
      accuracyCompareText = '与上周期持平'
    }
  }

  let questionsCompareText = '等待上周期数据'
  let questionsCompareClass = 'neutral'
  if (hasPrevious) {
    if (previousTotalQuestions > 0) {
      const changePct = Math.round((totalQuestions - previousTotalQuestions) / previousTotalQuestions * 100)
      if (changePct > 0) {
        questionsCompareText = `较上周期 +${changePct}%`
        questionsCompareClass = 'up'
      } else if (changePct < 0) {
        questionsCompareText = `较上周期 ${changePct}%`
        questionsCompareClass = 'down'
      } else {
        questionsCompareText = '与上周期持平'
      }
    } else if (totalQuestions > 0) {
      questionsCompareText = '本周期开始产生学习记录'
      questionsCompareClass = 'up'
    } else {
      questionsCompareText = '两周期均暂无做题记录'
    }
  }

  let statusTitle = '正在积累学习数据'
  if (totalQuestions > 0) {
    if (avgPct >= 85 && activeDays >= 4) statusTitle = '状态很稳，继续保持'
    else if (avgPct >= 70) statusTitle = '节奏不错，稳步提升'
    else if (avgPct >= 50) statusTitle = '正在进入状态'
    else if (activeDays <= 2) statusTitle = '需要重新找回节奏'
    else statusTitle = '基础还需要巩固'
  }

  return {
    days: tr.days || 7,
    points,
    previousPoints,
    totalQuestions,
    activeDays,
    avgAccuracy,
    avgAccuracyPct: avgPct,
    previousTotalQuestions,
    previousActiveDays,
    previousAvgAccuracy,
    previousAvgAccuracyPct: previousAvgPct,
    hasPrevious,
    accuracyCompareText,
    accuracyCompareClass,
    questionsCompareText,
    questionsCompareClass,
    summary: tr.summary || '',
    statusTitle,
  }
}

/**
 * Build subjects view-model from SubjectAnalysisV2.
 * Enriched with weak topics, avg time, suggestion when insights data available.
 */
function buildSubjects(sa, enrichedMap) {
  if (!sa || !sa.items || !sa.items.length) return null
  const items = sa.items.map((s, i) => {
    const acc = s.accuracy || 0
    const subjectId = s.subject_id != null ? s.subject_id : (s.id != null ? s.id : null)
    const subjectCode = s.subject_code || ''
    const subjectName = s.subject_name || s.label || ''
    const enriched = (enrichedMap && (subjectId != null ? enrichedMap[subjectId] : enrichedMap[subjectCode])) || {}
    const totalQuestions = s.total_questions != null ? s.total_questions : (s.totalQuestions || 0)
    const correctCount = s.correct_count != null ? s.correct_count : (s.correctCount || 0)
    const wrongCount = s.wrong_count != null ? s.wrong_count : (s.wrongCount || 0)
    const totalDurationSec = s.total_duration_sec != null ? s.total_duration_sec : (s.totalDurationSec || 0)
    const avgTime = totalDurationSec > 0 && totalQuestions > 0
      ? Math.round(totalDurationSec / totalQuestions)
      : (s.avgTimeSec || 0)
    const baseWeakTopics = enriched.weak_topics || s.weakTopics || []
    return {
      subject_id: subjectId,
      subjectId,
      subject: subjectCode,
      subjectCode,
      subjectName,
      label: s.label || subjectName || subjectLabel(subjectCode),
      totalQuestions,
      correctCount,
      wrongCount,
      accuracy: acc,
      accuracyPct: accuracyPct(acc),
      barWidthPct: Math.max(2, Math.min(80, accuracyPct(acc) * 0.8)),
      valueLeftPct: Math.max(4, Math.min(84, accuracyPct(acc) * 0.8 + 2)),
      accuracyClass: accuracyClass(acc),
      accuracyColor: acc >= 0.7 ? '#22C55E' : acc >= 0.4 ? '#F59E0B' : '#EF4444',
      color: s.color || SUBJECT_COLORS[i % SUBJECT_COLORS.length],
      totalDurationSec,
      durationText: fmtDuration(totalDurationSec),
      avgTimeSec: avgTime,
      avgTimeText: avgTime > 0 ? '均时' + avgTime + 's' : '',
      weakTopics: baseWeakTopics.slice(0, 3).map(w => w.name || w),
      suggestion: enriched.suggestion || s.suggestion || '',
      repeatWrongCount: enriched.repeat_wrong_count || s.repeatWrongCount || 0,
      statusLabel: enriched.status_label || s.statusLabel || '',
    }
  })
  const itemsByWeak = items.slice().sort((a, b) => {
    if (a.accuracy !== b.accuracy) return a.accuracy - b.accuracy
    return b.wrongCount - a.wrongCount
  })
  const strongestLabel = typeof sa.strongest === 'string'
    ? sa.strongest
    : (sa.strongest && (sa.strongest.subject_name || sa.strongest.subject)
        ? (sa.strongest.subject_name || subjectLabel(sa.strongest.subject))
        : null)
  const weakestLabel = typeof sa.weakest === 'string'
    ? sa.weakest
    : (sa.weakest && (sa.weakest.subject_name || sa.weakest.subject)
        ? (sa.weakest.subject_name || subjectLabel(sa.weakest.subject))
        : null)
  return {
    items,
    itemsByWeak,
    focusItem: itemsByWeak[0] || null,
    strongest: strongestLabel,
    weakest: weakestLabel,
    totalQuestions: sa.total_questions != null
      ? sa.total_questions
      : (sa.totalQuestions != null ? sa.totalQuestions : items.reduce((sum, item) => sum + item.totalQuestions, 0)),
  }
}

/**
 * Build review risk view-model.
 */
function buildReviewRisk(rr) {
  if (!rr) return null
  const total = (rr.high_forget_count || 0) + (rr.stuck_questions || 0) + (rr.pseudo_mastered_count || 0)
  if (total === 0) return { hasRisk: false, riskFree: true, highForgetCount: 0, stuckQuestions: 0, pseudoMasteredCount: 0, topTopics: [] }
  return {
    hasRisk: true,
    riskFree: false,
    highForgetCount: rr.high_forget_count || 0,
    stuckQuestions: rr.stuck_questions || 0,
    pseudoMasteredCount: rr.pseudo_mastered_count || 0,
    topTopics: (rr.top_topics || []).slice(0, 5),
  }
}

/**
 * Build growth view-model (featured badges only).
 */
function buildGrowth(g) {
  if (!g) return null
  return {
    level: g.level || 1,
    levelTitle: g.level_title || '',
    levelProgressPct: g.level_progress_pct || 0,
    streakTitle: g.streak_title || '',
    featuredBadges: (g.featured_badges || []).slice(0, 3),
  }
}

/**
 * Build adaptive view-model.
 */
function buildAdaptive(a) {
  if (!a || !a.visible) return null
  return {
    intervalStatusLabel: a.interval_status_label || '节奏正常',
    recallPct: Math.round((a.recent_due_recall_rate || 0) * 100),
    targetPct: Math.round((a.target_recall_rate || 0.8) * 100),
    summary: a.summary || '',
  }
}

/**
 * Build yearly summary view-model.
 */
function buildYearly(ys) {
  if (!ys) return null
  return {
    activeDays: ys.active_days || 0,
    totalQuestions: ys.total_questions || 0,
    bestDayText: ys.best_day_text || '暂无记录',
  }
}

/**
 * Build suggestion subtitle text for hero area.
 */
function buildSubtitle(hero, rec, reviewRisk) {
  if (!hero || hero.totalQuestions === 0) return '完成第一道题后，这里会生成学习报告'
  if (hero.dueReviewCount > 0) return `还有 ${hero.dueReviewCount} 道到期复习，建议优先完成`
  if (hero.todayQuestions > 0) return `今天已完成 ${hero.todayQuestions} 题，继续保持节奏`
  if (rec) return rec.desc
  return '开始今日练习，积累更多学习数据'
}

/**
 * Build mastery status text based on percentage.
 */
function buildMasteryStatus(pct) {
  if (pct <= 0) return '先从错题复盘开始'
  if (pct < 60) return '仍有较多错题待巩固'
  if (pct < 90) return '掌握情况正在提升'
  return '错题掌握较好'
}

module.exports = {
  subjectLabel,
  fmtDuration,
  accuracyPct,
  accuracyClass,
  buildHero,
  buildTrends,
  buildSubjects,
  buildReviewRisk,
  buildGrowth,
  buildAdaptive,
  buildYearly,
  buildSubtitle,
  buildMasteryStatus,
  buildInsights,
  buildTodayQuality,
  buildWeeklyConsistency,
  buildWeakTopics,
  buildRepeatWrong,
  buildSpeedAccuracy,
  buildNewVsReview,
  buildInputOutput,
}

// ──────────────────────────────────────────────
// Dashboard insights (刷题诊断) builders
// ──────────────────────────────────────────────

/**
 * Top-level insight aggregator. Returns null when no actionable data.
 */
function buildInsights(data) {
  if (!data) return null
  const hasAny = Object.values(data).some(v => v && v.data_available !== false)
  if (!hasAny) return null
  return {
    todayQuality: buildTodayQuality(data.today_quality),
    weeklyConsistency: buildWeeklyConsistency(data.weekly_consistency),
    weakTopics: buildWeakTopics(data.weak_topic_ranking),
    repeatWrong: buildRepeatWrong(data.repeat_wrong_analysis),
    speedAccuracy: buildSpeedAccuracy(data.speed_accuracy),
    newVsReview: buildNewVsReview(data.new_vs_review),
    inputOutput: buildInputOutput(data.input_output),
  }
}

function buildTodayQuality(tq) {
  if (!tq || !tq.data_available) return null
  const score = tq.score || 0
  return {
    score,
    displayScore: Math.round(score),
    label: tq.label || '数据不足',
    questions: tq.questions || 0,
    accuracyPct: Math.round((tq.accuracy || 0) * 100),
    avgTimeSec: tq.avg_time_sec || 0,
    scoreColor: score >= 80 ? '#22C55E' : score >= 60 ? '#4F7FFF' : score >= 40 ? '#F59E0B' : '#EF4444',
    labelClass: score >= 80 ? 'green' : score >= 60 ? 'primary' : score >= 40 ? 'orange' : 'red',
  }
}

function buildWeeklyConsistency(wc) {
  if (!wc || !wc.data_available) return null
  const score = wc.score || 0
  return {
    score,
    displayScore: Math.round(score),
    label: wc.label || '数据不足',
    activeDays: wc.active_days || 0,
    days: wc.days || 7,
    totalQuestions: wc.total_questions || 0,
    dayBreakdown: wc.day_breakdown || [],
    scoreColor: score >= 80 ? '#22C55E' : score >= 60 ? '#4F7FFF' : '#F59E0B',
  }
}

function buildWeakTopics(wt) {
  if (!wt || !wt.data_available || !wt.items || !wt.items.length) return null
  const items = wt.items.map((t, i) => ({
    knowledgePointId: t.knowledge_point_id,
    name: t.name,
    subject: t.subject || '',
    subjectId: t.subject_id != null ? t.subject_id : (t.subject || null),
    subjectLabel: t.subject_label || t.subject_name || t.subject || '',
    masteryScore: Math.round(t.mastery_score || 0),
    attemptCount: t.attempt_count || 0,
    wrongCount: t.wrong_count || 0,
    recentWrongCount: t.recent_wrong_count || 0,
    dueReviewCount: t.due_review_count || 0,
    lastPracticedAt: t.last_practiced_at,
    rank: i + 1,
    rankColor: i === 0 ? '#EF4444' : i === 1 ? '#F59E0B' : i === 2 ? '#4F7FFF' : '#8EA0BA',
    masteryClass: t.mastery_score < 30 ? 'danger' : t.mastery_score < 50 ? 'warning' : 'primary',
  }))
  return { items, totalCount: items.length }
}

function buildRepeatWrong(rw) {
  if (!rw || !rw.data_available) return null
  return {
    dataAvailable: true,
    repeatWrongCount: rw.repeat_wrong_count || 0,
    totalWrongCount: rw.total_wrong_count || 0,
    repeatRate: rw.repeat_rate || 0,
    repeatRatePct: Math.round((rw.repeat_rate || 0) * 100),
    isHigh: !!rw.is_high,
    statusLabel: rw.status_label || '较低',
    topRepeatTopics: (rw.top_repeat_topics || []).slice(0, 5),
  }
}

function buildSpeedAccuracy(sa) {
  if (!sa || !sa.data_available) return null
  let conclusion = ''
  switch (sa.overall_status) {
    case 'knowledge_gap':
      conclusion = '知识点不熟，建议回归教材巩固理解'
      break
    case 'hasty':
      conclusion = '审题不稳，建议放慢速度仔细审题'
      break
    case 'unfamiliar':
      conclusion = '解法不熟，建议多做同类题目巩固'
      break
    default:
      conclusion = '速度正常，继续保持'
  }
  return {
    dataAvailable: true,
    overallStatus: sa.overall_status || 'normal',
    overallLabel: sa.overall_label || '速度正常',
    conclusion,
    avgTimeCorrectSec: sa.avg_time_correct_sec || 0,
    avgTimeWrongSec: sa.avg_time_wrong_sec || 0,
    fastWrongCount: sa.fast_wrong_count || 0,
    slowWrongCount: sa.slow_wrong_count || 0,
    bySubject: (sa.by_subject || []).map(s => ({
      subject: s.subject_code || s.subject || '',
      subjectLabel: s.subject_name || s.subject_code || s.subject_label || s.subject || '',
      avgTimeCorrectSec: s.avg_time_correct_sec || 0,
      avgTimeWrongSec: s.avg_time_wrong_sec || 0,
      questions: s.questions || 0,
      statusLabel: s.status_label || '',
    })),
  }
}

function buildNewVsReview(nr) {
  if (!nr || !nr.data_available) return null
  return {
    dataAvailable: true,
    newCount: nr.new_count || 0,
    newAccuracyPct: Math.round((nr.new_accuracy || 0) * 100),
    reviewCount: nr.review_count || 0,
    reviewAccuracyPct: Math.round((nr.review_accuracy || 0) * 100),
    label: nr.label || '数据不足',
    summary: nr.summary || '',
  }
}

function buildInputOutput(io) {
  if (!io || !io.data_available) return null
  return {
    dataAvailable: true,
    globalAvgTimeSec: io.global_avg_time_sec || 0,
    items: (io.items || []).map(i => ({
      subject: i.subject_code || i.subject || '',
      subjectLabel: i.subject_name || i.subject_code || i.subject_label || i.subject || '',
      totalQuestions: i.total_questions || 0,
      totalDurationSec: i.total_duration_sec || 0,
      accuracyPct: Math.round((i.accuracy || 0) * 100),
      timePerQuestionSec: i.time_per_question_sec || 0,
      efficiencyScore: i.efficiency_score || 0,
      efficiencyLabel: i.efficiency_label || '数据不足',
      suggestion: i.suggestion || '',
    })),
  }
}

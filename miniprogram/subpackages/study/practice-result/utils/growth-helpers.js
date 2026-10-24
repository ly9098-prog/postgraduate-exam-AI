/**
 * Pure helpers for growth profile normalization,
 * extracted from practice-result/index.js.
 */

var DEFAULT_GROWTH = {
  total_exp: 0,
  level: 1,
  level_title: '起步',
  levelTitle: '起步',
  level_progress_pct: 0,
  exp_current: 0,
  exp_to_next: 200,
  streak_days: 0,
  streak_title: '',
  daily_boost: '',
  badges: []
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function stripLevelPrefix(title, level) {
  var text = String(title || '').trim()
  if (!text) return level === 1 ? '起步' : ''
  return text.replace(/^Lv\s*\d+\s*/i, '').trim() || text
}

function growthFromTotalExp(totalExp, streakDays, badges) {
  var total = Math.max(0, Math.round(Number(totalExp) || 0))
  var levels = [
    { lo: 0, hi: 200, level: 1, title: 'Lv1 起步' },
    { lo: 200, hi: 600, level: 2, title: 'Lv2 坚持者' },
    { lo: 600, hi: 1500, level: 3, title: 'Lv3 刷题达人' },
    { lo: 1500, hi: 3500, level: 4, title: 'Lv4 高效进阶' },
    { lo: 3500, hi: null, level: 5, title: 'Lv5 上岸冲刺' }
  ]
  var current = levels[0]
  levels.forEach(function(item) { if (total >= item.lo) current = item })
  var expCurrent = Math.max(0, total - current.lo)
  var expToNext = current.hi === null ? 0 : current.hi - current.lo
  var progress = current.hi === null ? 100 : Math.min(100, Math.round(expCurrent / expToNext * 100))
  return {
    total_exp: total,
    level: current.level,
    level_title: current.title,
    levelTitle: stripLevelPrefix(current.title, current.level),
    level_progress_pct: progress,
    exp_current: expCurrent,
    exp_to_next: expToNext,
    streak_days: Math.max(0, Number(streakDays) || 0),
    streak_title: '',
    daily_boost: '',
    badges: Array.isArray(badges) ? badges : []
  }
}

function normalizeGrowthProfile(raw) {
  if (!raw || typeof raw !== 'object') return null
  var source = raw.growth && typeof raw.growth === 'object' ? raw.growth : raw
  var level = Math.max(1, Number(source.level) || 1)
  var levelTitleFull = source.level_title || source.levelTitle || ('Lv' + level + ' ' + (level === 1 ? '起步' : '')).trim()
  var totalExpValue = Number(source.total_exp != null ? source.total_exp : source.totalExp)
  var expCurrentValue = Number(source.exp_current != null ? source.exp_current : source.expCurrent)
  var expToNextValue = Number(source.exp_to_next != null ? source.exp_to_next : source.expToNext)
  var progressValue = Number(source.level_progress_pct != null ? source.level_progress_pct : source.levelProgressPct)
  var totalExp = Number.isFinite(totalExpValue) ? Math.max(0, totalExpValue) : 0
  var expCurrent = Number.isFinite(expCurrentValue) ? Math.max(0, expCurrentValue) : 0
  var expToNext = Number.isFinite(expToNextValue) ? Math.max(0, expToNextValue) : (level >= 5 ? 0 : 200)
  var progress = Number.isFinite(progressValue) ? clamp(progressValue, 0, 100) : (expToNext > 0 ? Math.round(expCurrent / expToNext * 100) : (level >= 5 ? 100 : 0))
  if (progress === 0 && expCurrent > 0 && expToNext > 0) {
    progress = Math.min(100, Math.round(expCurrent / expToNext * 100))
  }
  return Object.assign({}, DEFAULT_GROWTH, source, {
    total_exp: totalExp,
    level: level,
    level_title: levelTitleFull,
    levelTitle: stripLevelPrefix(levelTitleFull, level),
    level_progress_pct: progress,
    exp_current: expCurrent,
    exp_to_next: expToNext,
    streak_days: Math.max(0, Number(source.streak_days != null ? source.streak_days : source.streakDays) || 0),
    badges: Array.isArray(source.badges) ? source.badges : []
  })
}

function growthFromOverview(overview) {
  if (!overview || typeof overview !== 'object') return null
  var totalQuestions = Math.max(0, Number(overview.total_questions != null ? overview.total_questions : overview.totalQuestions) || 0)
  var accuracyRaw = Number(overview.accuracy)
  var accuracy = Number.isFinite(accuracyRaw) ? (accuracyRaw > 1 ? accuracyRaw / 100 : accuracyRaw) : 0
  var streak = Math.max(0, Number(overview.consecutive_days != null ? overview.consecutive_days : overview.consecutiveDays) || 0)
  var mastered = Math.max(0, Number(overview.mastered_count != null ? overview.mastered_count : overview.masteredCount) || 0)
  var totalExp = totalQuestions * 10 + mastered * 20 + streak * 5
  if (accuracy >= 0.7 && totalQuestions >= 10) {
    totalExp += Math.floor(totalQuestions * accuracy * 5)
  }
  return growthFromTotalExp(totalExp, streak)
}

module.exports = {
  DEFAULT_GROWTH,
  stripLevelPrefix,
  growthFromTotalExp,
  normalizeGrowthProfile,
  growthFromOverview,
}

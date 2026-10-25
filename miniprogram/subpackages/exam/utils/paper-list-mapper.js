function minutes(sec) {
  const value = Number(sec || 0)
  return value > 0 ? Math.max(1, Math.round(value / 60)) : 0
}

function cleanUiLabel(value, fallback = '') {
  return String(value || fallback).replace(/408/g, '').replace(/\s{2,}/g, ' ').trim()
}

function typeLabel(type) {
  return type === 'past_exam_choice' ? '真题选择题' : '选择题模拟卷'
}

function typeHint(type) {
  return type === 'past_exam_choice'
    ? '历年真题 · 只做适合手机作答的选择题'
    : '模拟训练 · 只做适合手机作答的选择题'
}

function buildPapers(rows, suggestedPaperId) {
  const basePapers = (Array.isArray(rows) ? rows : []).map((item) => ({
    ...item,
    title: cleanUiLabel(item.title, '选择题套卷'),
    source: cleanUiLabel(item.source, 'MemoGrad'),
    typeLabel: typeLabel(item.paper_type),
    typeHint: typeHint(item.paper_type),
    durationMinutes: minutes(item.duration_sec),
    scoreText: Number(item.total_choice_score || 0).toFixed(0),
    bestScoreText: item.best_choice_score == null ? '' : Number(item.best_choice_score).toFixed(1),
    canResume: item.latest_attempt_status === 'in_progress' && !!item.latest_attempt_id,
    isSuggested: Number(item.id) === Number(suggestedPaperId),
  }))

  const latestYear = basePapers.reduce((maxYear, item) => {
    const year = Number(item.year) || 0
    return year > maxYear ? year : maxYear
  }, 0)

  return basePapers.map((item) => ({
    ...item,
    isLatestYear: !!latestYear && Number(item.year) === latestYear,
  }))
}

module.exports = {
  buildPapers,
  cleanUiLabel,
  minutes,
  typeHint,
  typeLabel,
}

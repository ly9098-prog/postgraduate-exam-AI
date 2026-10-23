function normalizeOverview(overview) {
  const source = overview || {}
  return {
    stats: source.stats || {},
    trends: (source.trends || []).map(item => ({
      date: item.date,
      duration_sec: item.duration_sec,
      _shortDate: (item.date || '').slice(5),
    })),
    summary: source.daily_summary || {},
    lifetime: source.lifetime_summary || {},
  }
}

function hasCrossDayBleedInSubjects(subjects) {
  return (subjects || []).some(
    item => Number(item && item.duration_sec) > 0 && Number(item && item.sessions) === 0
  )
}

function buildTrendItems(trends) {
  return (trends || []).map(item => ({
    date: item.date,
    duration_sec: item.duration_sec,
    _shortDate: (item.date || '').slice(5),
  }))
}

module.exports = {
  normalizeOverview,
  hasCrossDayBleedInSubjects,
  buildTrendItems,
}

const subjectDistribution = require('./subject-distribution')
const durationFormatter = require('./duration-formatter')

const DARK_SUBJECT_COLORS = ['#3B82F6', '#F59E0B', '#10B981', '#06B6D4', '#F97316', '#2DD4BF', '#EA580C', '#8B5CF6', '#6366F1', '#EC4899']
const LIGHT_SUBJECT_COLORS = ['#2F6B4F', '#7A9B76', '#2B8C83', '#B59A38', '#C4773B', '#D96B5F', '#6685A3', '#718C45', '#B45E46', '#876F8F']
const LIGHT_PIE_COLORS = ['#E76F51', '#2A9D8F', '#457B9D', '#E9C46A', '#8E6BBE', '#F28482', '#6A994E', '#43AA8B', '#B56576', '#577590']

function getColorBySubject(subject, colors) {
  let hash = 0
  const str = subject || ''
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

function getPieSubjectColor(subject, themeMode) {
  const colors = themeMode === 'light' ? LIGHT_PIE_COLORS : DARK_SUBJECT_COLORS
  return getColorBySubject(subject, colors)
}

function getSubjectColor(subject, themeMode) {
  const colors = themeMode === 'light' ? LIGHT_SUBJECT_COLORS : DARK_SUBJECT_COLORS
  return getColorBySubject(subject, colors)
}

/**
 * Normalizes a raw subject distribution and decorates it with the view-model
 * fields used by the pie chart and detail popup.  All inputs are explicit so
 * callers remain responsible for supplying the current subject tree, theme,
 * and raw distribution.
 */
function buildSubjectItems(subjects, subjectMeta, themeMode) {
  const normalized = subjectDistribution.normalizeDistributionSubjects(subjects, subjectMeta)
  const totalDur = Math.max(1, normalized.reduce((sum, item) => sum + (item.duration_sec || 0), 0))
  return normalized.map(item => {
    const dur = item.duration_sec || 0
    const pct = dur / totalDur
    const code = item.subject_code || ''
    const subjectId = item.subject_id != null ? item.subject_id : null
    return {
      subject: subjectId != null ? subjectId : (code || 'uncategorized'),
      subject_id: subjectId,
      subject_code: code,
      duration_sec: dur,
      sessions: item.sessions || 0,
      participation_sessions: item.participation_sessions || 0,
      _label: item.subject_name || '未分类',
      _color: getPieSubjectColor(subjectId != null ? String(subjectId) : (code || '未分类'), themeMode),
      _durationText: durationFormatter.formatMin(dur),
      _durationBadgeText: durationFormatter.formatHourMinute(dur),
      _pct: pct,
      _pctText: (pct * 100).toFixed(1) + '%',
    }
  })
}

module.exports = {
  buildSubjectItems,
  getColorBySubject,
  getSubjectColor,
  getPieSubjectColor,
  DARK_SUBJECT_COLORS,
  LIGHT_SUBJECT_COLORS,
  LIGHT_PIE_COLORS,
}

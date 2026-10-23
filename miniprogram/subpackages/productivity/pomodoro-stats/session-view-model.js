const chinaTime = require('../utils/china-time')
const { formatDuration } = require('./duration-formatter')

function formatSession(session, options) {
  const s = session || {}
  // Keep history formatting on China time regardless of device timezone.
  const timeStr = chinaTime.formatChinaTimeHM(s.start_time)
  const dateStr = chinaTime.formatChinaMonthDay(s.start_time)
  const durSec = s.actual_duration ?? s.actual_duration_sec ?? s.duration_sec ?? 0
  const subjectName = s.subject_name || '未分类'
  const subjectKey = s.subject_code || ''
  const isReview = s.record_type === 'review'
  const isPractice = s.record_type === 'practice' || isReview
  const isFree = s.preset === 'free'
  const isEqualCore = s.allocation_mode === 'equal_408_core_v1'
  const sessionTaskType = options.getTaskTypeLabel(s)
  const durationText = formatDuration(durSec)

  let _subjectLabel, _statusLabel, _statusClass
  if (isPractice) {
    _subjectLabel = (isReview ? '复习 · ' : '刷题 · ') + subjectName
    _statusLabel = isReview ? '复习' : '刷题'
    _statusClass = 'status-done'
  } else {
    const attributedName = isEqualCore ? subjectName + '（四科均分）' : subjectName
    _subjectLabel = isFree ? '自由计时 · ' + attributedName : attributedName
    _statusLabel = s.status === 'completed' ? '完成' : '中断'
    _statusClass = s.status === 'completed' ? 'status-done' : 'status-interrupt'
  }

  return {
    ...s,
    _time: timeStr,
    _date: dateStr,
    _duration: durationText,
    _taskTypeLabel: sessionTaskType,
    _subjectLabel,
    _color: options.getSubjectColor(
      s.subject_id != null ? String(s.subject_id) : (subjectKey || subjectName)
    ),
    _statusLabel,
    _statusClass,
    _iconType: isPractice ? 'practice' : (isFree ? 'free' : 'focus'),
  }
}

module.exports = {
  formatSession,
}

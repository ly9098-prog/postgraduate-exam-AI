function createPomodoroRunningStateMigrator(options) {
  return {
    migrate: migrateImpl.bind(null, options),
  }
}

function migrateImpl(options, subjects) {
  const stored = options.safeGetPomodoroStorage('pomodoro_running_state', 'migrate running snapshot')
  if (!stored.ok) return false
  const local = stored.value
  if (!local || local.selectedSubjectId || !local.selectedSubjectCode) return true
  const match = (subjects || []).find(s => s.code === local.selectedSubjectCode)
  if (match) {
    local.selectedSubjectId = match.id
    if (!local.selectedSubjectName) local.selectedSubjectName = match.name || ''
    return options.safeSetPomodoroStorage('pomodoro_running_state', local, 'running snapshot refresh')
  }
  // 无法映射的旧 code 缓存 → 安全清除，避免恢复出无科目会话
  return options.safeRemovePomodoroStorage('pomodoro_running_state', 'stale running snapshot')
}

module.exports = {
  createPomodoroRunningStateMigrator,
}

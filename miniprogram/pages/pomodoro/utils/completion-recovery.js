function buildCompletionRecovery(completion, current, taskTypes) {
  const aggregate = completion.allocationMode === 'equal_408_core_v1'
  const selectedSubjectId = completion.selectedSubjectId || current.selectedSubjectId
  const selectedSubject = selectedSubjectId ? {
    id: selectedSubjectId,
    code: completion.selectedSubjectCode || (current.selectedSubject && current.selectedSubject.code) || '',
    name: completion.selectedSubjectName || (current.selectedSubject && current.selectedSubject.name) || '',
    _isAggregate: aggregate,
  } : current.selectedSubject
  const hasTaskType = Object.prototype.hasOwnProperty.call(completion, 'selectedTaskType')
  const taskType = hasTaskType && taskTypes.TYPE_MAP[completion.selectedTaskType]
    ? completion.selectedTaskType : ''
  return {
    breakSec: completion.breakSec !== undefined && Number.isFinite(Number(completion.breakSec))
      ? Math.max(0, Number(completion.breakSec)) : null,
    view: {
      phase: 'idle',
      isPaused: false,
      showEndConfirm: false,
      showCelebration: true,
      celebrationMotto: completion.motto,
      celebrationType: completion.type || 'excellent',
      selectedPreset: completion.selectedPreset || current.selectedPreset,
      workDuration: Number.isFinite(Number(completion.workDuration))
        ? Number(completion.workDuration) : current.workDuration,
      breakDuration: Number.isFinite(Number(completion.breakDuration))
        ? Number(completion.breakDuration) : current.breakDuration,
      selectedSubjectId,
      selectedSubject,
      allocationMode: aggregate ? 'equal_408_core_v1' : 'single',
      selectedTaskType: hasTaskType ? taskType : current.selectedTaskType,
      selectedTaskTypeLabel: hasTaskType
        ? (taskType ? taskTypes.label(taskType) : '未分类') : current.selectedTaskTypeLabel,
    },
  }
}

module.exports = { buildCompletionRecovery }

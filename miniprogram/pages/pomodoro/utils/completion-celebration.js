const { pomodoroTaskTypes } = require('../../../utils/storage')

function pickMotto(mottoes, MathRandom) {
  const idx = Math.floor((typeof MathRandom === 'function' ? MathRandom : Math.random)() * mottoes.length)
  return mottoes[idx]
}

function resolveTaskType(opts, data) {
  const hasOptionTaskType = Object.prototype.hasOwnProperty.call(opts, 'selectedTaskType')
  const rawTaskType = hasOptionTaskType ? opts.selectedTaskType : data.selectedTaskType
  return pomodoroTaskTypes.TYPE_MAP[rawTaskType] ? rawTaskType : ''
}

function buildCompletionFlag(sessionId, opts, resolved) {
  const { workDuration, breakDuration, selectedPreset, selectedSubject, selectedSubjectId,
    selectedTaskType, selectedTaskTypeLabel, motto, type, breakSec } = resolved
  return {
    motto, type, sessionId, breakSec, workDuration, breakDuration, selectedPreset,
    selectedSubjectId,
    selectedSubjectCode: selectedSubject ? selectedSubject.code || '' : '',
    selectedSubjectName: selectedSubject ? selectedSubject.name || '' : '',
    allocationMode: selectedSubject && selectedSubject._isAggregate
      ? 'equal_408_core_v1' : 'single',
    selectedTaskType,
  }
}

function buildCelebrationViewData(resolved) {
  const { motto, type, selectedPreset, workDuration, breakDuration,
    selectedSubjectId, selectedSubject, selectedTaskType, selectedTaskTypeLabel } = resolved
  return {
    phase: 'idle', isPaused: false, showEndConfirm: false,
    ringCanvasVisible: false, ringCanvasPaintReady: false,
    showCelebration: true, celebrationMotto: motto, celebrationType: type,
    selectedPreset, workDuration, breakDuration,
    selectedSubjectId, selectedSubject, selectedTaskType, selectedTaskTypeLabel,
  }
}

function buildCompletionCelebration(sessionId, options, context) {
  const opts = options || {}
  const data = context.data
  const workDuration = Number.isFinite(Number(opts.workDuration)) ? Number(opts.workDuration) : data.workDuration
  const breakDuration = Number.isFinite(Number(opts.breakDuration)) ? Number(opts.breakDuration) : data.breakDuration
  const selectedPreset = opts.selectedPreset || data.selectedPreset
  const selectedSubject = opts.selectedSubject || data.selectedSubject
  const selectedSubjectId = opts.selectedSubjectId || data.selectedSubjectId || (selectedSubject && selectedSubject.id) || null
  const selectedTaskType = resolveTaskType(opts, data)
  const selectedTaskTypeLabel = selectedTaskType
    ? (opts.selectedTaskTypeLabel || pomodoroTaskTypes.label(selectedTaskType)) : '未分类'
  const breakSec = selectedPreset === 'debug' ? 5 : Math.max(0, breakDuration * 60)
  const motto = opts.motto || pickMotto(context.mottoes, context.MathRandom)
  const type = opts.type || context.nextCelebrationType()
  const resolved = { workDuration, breakDuration, selectedPreset, selectedSubject,
    selectedSubjectId, selectedTaskType, selectedTaskTypeLabel, motto, type, breakSec }
  return {
    completionFlag: buildCompletionFlag(sessionId, opts, resolved),
    viewData: buildCelebrationViewData(resolved),
    breakSec, selectedTaskType, sessionId,
  }
}

module.exports = { buildCompletionCelebration, pickMotto }

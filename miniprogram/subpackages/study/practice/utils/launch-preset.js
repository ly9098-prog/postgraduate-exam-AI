function parseLaunchPreset(options, safeDecode) {
  const subjectId = Number(options && options.subject_id)
  const subjectCode = String((options && options.subject_code) || '').trim().slice(0, 64)
  const modeValue = String((options && options.mode) || '').trim()
  const allowedModes = new Set(['random', 'smart', 'sequential'])
  const rawCount = Number(options && options.count)
  const count = Number.isFinite(rawCount) ? Math.max(1, Math.min(50, Math.round(rawCount))) : null
  const knowledgePoint = safeDecode(options && options.knowledge_point, '').trim()
  const knowledgePointId = Number(options && options.knowledge_point_id)
  const rawQuestionIds = String((options && options.question_ids) || '').trim()
  let questionIds = ''
  if (rawQuestionIds) {
    const parsed = rawQuestionIds
      .split(',')
      .map(value => Number(String(value || '').trim()))
      .filter(value => Number.isInteger(value) && value > 0)
    const unique = Array.from(new Set(parsed)).slice(0, 50)
    if (unique.length === parsed.length && unique.length > 0) questionIds = unique.join(',')
  }
  return {
    subjectId: Number.isInteger(subjectId) && subjectId > 0 ? subjectId : null,
    mode: allowedModes.has(modeValue) ? modeValue : null,
    count,
    knowledgePoint,
    knowledgePointId: Number.isInteger(knowledgePointId) && knowledgePointId > 0 ? knowledgePointId : null,
    questionIds,
    allowRepeat: String((options && options.allow_repeat) || '') === '1',
    autostart: String((options && options.autostart) || '') === '1',
    source: String((options && options.source) || '').trim().slice(0, 32),
    planToken: String((options && options.plan_token) || '').trim().slice(0, 2048),
    subjectName: safeDecode(options && options.subject_name, '').trim().slice(0, 80),
    includeChildren: String((options && options.include_children) || '') === '1',
    includeDescendants: String((options && options.include_descendants) || '') === '1',
    subjectCode,
    returnTo: normalizePracticeReturnRoute(options && options.return_to, safeDecode),
  }
}

function normalizePracticeReturnRoute(value, safeDecode) {
  const route = safeDecode(value, '').trim().slice(0, 512)
  if (!route) return ''
  if (!/^\/subpackages\/study\/knowledge-(?:detail|subject)\/index(?:\?.*)?$/.test(route)) return ''
  return route
}

function launchPresetOverrides(preset) {
  return {
    knowledgePoint: preset.questionIds ? '' : preset.knowledgePoint,
    knowledgePointId: preset.questionIds ? null : preset.knowledgePointId,
    includeDescendants: Boolean(!preset.questionIds && preset.includeDescendants && preset.knowledgePointId),
    questionIds: preset.questionIds,
    allowRepeat: Boolean(preset.allowRepeat || preset.questionIds),
    source: preset.source,
    planToken: preset.planToken || '',
    returnTo: preset.returnTo || '',
  }
}

function fastLaunchPresetView(preset, selectedMode, selectedCount) {
  return {
    mode: preset.questionIds ? 'random' : (preset.mode || 'random'),
    count: preset.questionIds
      ? preset.questionIds.split(',').length
      : (preset.count || selectedCount || 5),
    selectedSubjectId: Number(preset.subjectId),
    selectedSubjectName: preset.subjectName || '专项练习',
    selectedSubjectHasChildren: Boolean(preset.includeChildren || preset.knowledgePointId),
    expandedSubjectId: Number(preset.subjectId),
  }
}

function resolvedLaunchPresetView(preset, target, selectedMode, selectedCount) {
  return {
    mode: preset.questionIds ? 'random' : (preset.mode || selectedMode || 'random'),
    count: preset.questionIds
      ? preset.questionIds.split(',').length
      : (preset.count || selectedCount || 5),
    selectedSubjectId: Number(target.subject_id),
    selectedSubjectName: target.display_name,
    selectedSubjectHasChildren: Boolean(target.has_children),
    expandedSubjectId: target.parent_subject_id || target.subject_id,
  }
}

function applyLaunchOverrides(target, overrides) {
  target._launchKnowledgePoint = overrides.knowledgePoint
  target._launchKnowledgePointId = overrides.knowledgePointId
  target._launchIncludeDescendants = overrides.includeDescendants
  target._launchQuestionIds = overrides.questionIds
  target._launchAllowRepeat = overrides.allowRepeat
  target._launchSource = overrides.source
  target._launchPlanToken = overrides.planToken
  target._launchReturnTo = overrides.returnTo
}

module.exports = {
  parseLaunchPreset,
  launchPresetOverrides,
  fastLaunchPresetView,
  resolvedLaunchPresetView,
  applyLaunchOverrides,
}

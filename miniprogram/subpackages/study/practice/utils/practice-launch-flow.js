async function _applyFastLaunchPreset(page, dependencies) {
const { applyLaunchOverrides, fastLaunchPresetView, launchPresetOverrides } = dependencies
const preset = page._launchPreset
if (!preset || !preset.subjectId || !preset.autostart) return false
const subjectName = preset.subjectName || page.data.selectedSubjectName || '专项练习'
applyLaunchOverrides(page, launchPresetOverrides(preset))
await new Promise(resolve => {
const view = fastLaunchPresetView(preset, page.data.selectedMode, page.data.count)
view.selectedSubjectName = subjectName
page.setData(view, () => {
page._updateComputedFields()
resolve()
})
})
page._queueRememberSubject(Number(preset.subjectId), subjectName)
return true
}

async function _applyLaunchPreset(page, subjectTree, dependencies) {
const { applyLaunchOverrides, getConsole, getPlatform, launchPresetOverrides, resolvedLaunchPresetView } = dependencies
const preset = page._launchPreset
const available = page._flattenSelectableSubjects(subjectTree || [])
if (preset && preset.subjectCode && !preset.subjectId) {
const byCode = available.find(item => String(item.subject_code || '') === String(preset.subjectCode || ''))
if (byCode) preset.subjectId = Number(byCode.subject_id)
}
if (!preset || !preset.subjectId) return false
const target = available.find(item => Number(item.subject_id) === Number(preset.subjectId))
if (!target) {
getConsole().warn('[PRACTICE_LAUNCH_PRESET] subject unavailable', preset.subjectId)
if (preset.autostart) getPlatform().showToast({ title: '推荐科目已不可用，请重新选择', icon: 'none' })
return false
}
if (preset.questionIds && preset.mode && preset.mode !== 'random') {
getConsole().warn('[PRACTICE_LAUNCH_PRESET] targeted questions require random mode')
return false
}
applyLaunchOverrides(page, launchPresetOverrides(preset))
await new Promise((resolve) => {
const view = resolvedLaunchPresetView(preset, target, page.data.selectedMode, page.data.count)
page.setData(view, () => {
page._updateComputedFields()
resolve()
})
})
page._queueRememberSubject(Number(target.subject_id), target.display_name)
return true
}

function initDefaultSubject(page, subjectTree, dependencies) {
const { RECENT_SUBJECTS_STORAGE_KEY, getPlatform, selectDefaultSubject } = dependencies
if (!subjectTree || subjectTree.length === 0) {
page.setData({
selectedSubjectId: null,
selectedSubjectName: '',
selectedSubjectHasChildren: false,
expandedSubjectId: null,
recentSubjects: [],
})
return
}
let stored = []
try {
if (!page.data.guestMode) {
const value = getPlatform().getStorageSync(RECENT_SUBJECTS_STORAGE_KEY)
stored = Array.isArray(value) ? value : []
}
} catch (e) {
stored = []
}
const selection = selectDefaultSubject({
subjectTree,
storedSubjects: stored,
flattenSelectableSubjects: tree => page._flattenSelectableSubjects(tree),
decorateRecentSubjects: subjects => page._decorateRecentSubjects(subjects),
})
if (selection) page.setData(selection.view)
}

function _clearLaunchOverridesForManualConfig(page) {
// Home/Study Hub route params are setup defaults, not invisible constraints.
// Once the user changes subject/mode/count, continuing to send the original KP or
// targeted-question scope can silently pin a parent-subject practice to one child
// subject and can also make the signed batch impossible to submit.
page._launchKnowledgePoint = ''
page._launchKnowledgePointId = null
page._launchIncludeDescendants = false
page._launchQuestionIds = ''
page._launchAllowRepeat = false
page._launchPlanToken = ''
}

function _buildQuestionRequestParams(page, dependencies) {
const { buildQuestionRequestParams } = dependencies
if (page.data.guestMode) return {
  subject_id: page.data.selectedSubjectId,
  include_children: page.data.selectedSubjectHasChildren,
  mode: 'random',
  count: page.data.count,
}
return buildQuestionRequestParams({
subjectId: page.data.selectedSubjectId,
selectedMode: page.data.selectedMode,
selectedSubjectHasChildren: page.data.selectedSubjectHasChildren,
count: page.data.count,
traceId: page._practiceSession.traceId,
launchQuestionIds: page._launchQuestionIds,
launchAllowRepeat: page._launchAllowRepeat,
launchPlanToken: page._launchPlanToken,
launchKnowledgePointId: page._launchKnowledgePointId,
launchIncludeDescendants: page._launchIncludeDescendants,
launchKnowledgePoint: page._launchKnowledgePoint,
})
}

function toggleSettings(page) {
page.setData({ settingsExpanded: !page.data.settingsExpanded })
}

module.exports = { _applyFastLaunchPreset, _applyLaunchPreset, initDefaultSubject, _clearLaunchOverridesForManualConfig, _buildQuestionRequestParams, toggleSettings }

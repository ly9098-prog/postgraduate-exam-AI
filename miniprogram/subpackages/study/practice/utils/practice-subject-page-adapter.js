function _recentSubjectController(page, dependencies) {
const { createRecentSubjectController, getConsole, getPlatform } = dependencies
return page._recentSubjectControllerInstance || (
page._recentSubjectControllerInstance = createRecentSubjectController({
findParentSubjectId: id => page._findParentSubjectId(id),
subjectHasChildren: id => page._subjectHasChildren(id),
getRecentSubjects: () => page.data.recentSubjects || [],
decorateRecentSubjects: subjects => page._decorateRecentSubjects(subjects),
setData: patch => page.setData(patch),
setStorage: (key, value) => getPlatform().setStorageSync(key, value),
logWarn: (...args) => getConsole().warn(...args),
getPending: () => page._pendingRememberSubject,
setPending: value => { page._pendingRememberSubject = value },
})
)
}

function _subjectSheetController(page, dependencies) {
const { createSubjectSheetController, getClearTimeout, getDate, getSetTimeout } = dependencies
return page._subjectSheetControllerInstance || (
page._subjectSheetControllerInstance = createSubjectSheetController({
getCloseTimer: () => page._subjectSheetCloseTimer,
setCloseTimer: timer => { page._subjectSheetCloseTimer = timer },
clearTimeout: timer => getClearTimeout()(timer),
setData: (patch, callback) => page.setData(patch, callback),
isVisible: () => page.data.subjectSheetVisible,
isClosing: () => page.data.subjectSheetClosing,
isPageAlive: () => page._pageAlive,
setTimeout: (callback, delay) => getSetTimeout()(callback, delay),
getLastTap: () => page._lastSubjectOptionTap,
setLastTap: value => { page._lastSubjectOptionTap = value },
now: () => getDate().now(),
closeSheet: () => page.closeSubjectSheet(),
})
)
}

function _subjectSelectionController(page, dependencies) {
const { createSubjectSelectionController } = dependencies
return page._subjectSelectionControllerInstance || (
page._subjectSelectionControllerInstance = createSubjectSelectionController({
getSelectedSubjectId: () => page.data.selectedSubjectId,
getSelectedMode: () => page.data.selectedMode,
getCount: () => page.data.count,
getExpandedSubjectId: () => page.data.expandedSubjectId,
findParentSubjectId: id => page._findParentSubjectId(id),
subjectHasChildren: id => page._subjectHasChildren(id),
clearLaunchOverrides: () => page._clearLaunchOverridesForManualConfig(),
queueRememberSubject: (id, name) => {
if (!page.data.guestMode) page._queueRememberSubject(id, name)
},
handleSubjectOptionTap: (id, source) => page._handleSubjectOptionTap(id, source),
setData: (patch, callback) => page.setData(patch, callback),
updateComputedFields: () => page._updateComputedFields(),
})
)
}

module.exports = { _recentSubjectController, _subjectSheetController, _subjectSelectionController }

function toggleTeacherActions(page) {
if (page.data.teacherLoadingAction) return
page.setData({ teacherActionsExpanded: !page.data.teacherActionsExpanded })
}

function _teacherCacheKeyForWrong(wq, diagnosis, action) {
const item = wq || {}
const d = diagnosis || {}
return [
Number(item.id || 0),
Number(item.question_id || item.questionId || 0),
Number(d.question_version_id || d.questionVersionId || item.question_version_id || item.questionVersionId || 0),
Number(d.id || 0),
String(action || ''),
String(item.wrong_answer || ''),
].join('|')
}

function close408TeacherSheet(page) {
page.setData({ teacherSheetVisible: false })
}

async function feedback408Teacher(page, e, deps) {
if (page.data.teacherFeedbackSent || !page.data.teacherResult) return
const type = String(e.currentTarget.dataset.type || '')
const wq = page.data.wq || {}
const questionId = Number(wq.question_id || wq.questionId || 0)
if (!type || !questionId) return
try {
await deps.teacher.submitFeedback(deps.requestClient, {
questionId,
feedbackType: type,
result: page.data.teacherResult,
})
if (page._activeTeacherCacheKey) {
if (!page._teacherFeedbackCache) page._teacherFeedbackCache = Object.create(null)
page._teacherFeedbackCache[page._activeTeacherCacheKey] = type
}
page.setData({ teacherFeedbackSent: type })
deps.platform.showToast({ title: '反馈已记录', icon: 'success' })
} catch (error) {
deps.platform.showToast({ title: deps.requestClient.getErrorMessage(error), icon: 'none' })
}
}

module.exports = { toggleTeacherActions, _teacherCacheKeyForWrong, close408TeacherSheet, feedback408Teacher }

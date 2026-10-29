function openDiagnosisSheet(page) {
const diagnosis = page.data.errorDiagnosis
const primary = diagnosis && diagnosis.primaryType && diagnosis.primaryType !== 'unknown'
? diagnosis.primaryType
: 'knowledge_gap'
const secondary = diagnosis && diagnosis.secondaryTypes && diagnosis.secondaryTypes.length
? diagnosis.secondaryTypes
: []
const secondaryMap = {}
secondary.forEach(type => { if (type && type !== primary) secondaryMap[type] = true })
page.setData({
diagnosisSheetVisible: true,
diagnosisPrimary: primary,
diagnosisSecondaryMap: secondaryMap,
})
}

function closeDiagnosisSheet(page) {
if (page.data.diagnosisSaving) return
page.setData({ diagnosisSheetVisible: false })
}

function selectDiagnosisPrimary(page, e) {
const type = e.currentTarget.dataset.type
if (!type) return
const secondaryMap = Object.assign({}, page.data.diagnosisSecondaryMap || {})
delete secondaryMap[type]
page.setData({ diagnosisPrimary: type, diagnosisSecondaryMap: secondaryMap })
}

function toggleDiagnosisSecondary(page, e, ports) {
const type = e.currentTarget.dataset.type
if (!type || type === page.data.diagnosisPrimary) return
const secondaryMap = Object.assign({}, page.data.diagnosisSecondaryMap || {})
if (secondaryMap[type]) delete secondaryMap[type]
else {
if (Object.keys(secondaryMap).length >= 3) {
ports.platform.showToast({ title: '次级错因最多选择 3 个', icon: 'none' })
return
}
secondaryMap[type] = true
}
page.setData({ diagnosisSecondaryMap: secondaryMap })
}

async function saveDiagnosis(page, ports) {
const wqId = Number(page._currentWqId || (page.data.wq && page.data.wq.id))
if (!wqId || page.data.diagnosisSaving) return
const primaryType = page.data.diagnosisPrimary || 'unknown'
const secondaryTypes = Object.keys(page.data.diagnosisSecondaryMap || {}).filter(type => type !== primaryType)
page.setData({ diagnosisSaving: true })
try {
const raw = await ports.requestClient.put(`/wrong-questions/${wqId}/diagnosis`, {
diagnosis_id: page.data.errorDiagnosis ? Number(page.data.errorDiagnosis.id || 0) || undefined : undefined,
primary_type: primaryType,
secondary_types: secondaryTypes,
})
if (!page._alive || wqId !== Number(page._currentWqId)) return
const responseDiagnosis = ports.errorDiagnosis.normalizeDiagnosis(raw)
// Saving is an explicit user confirmation. Keep that fact locally even when an
// older backend response omits/temporarily misreports user_confirmed. Preserve
// any server id so later edits still target the same occurrence diagnosis.
const responseId = Number(raw && (raw.id || raw.diagnosis_id || (raw.diagnosis && raw.diagnosis.id)) || 0) || undefined
const currentId = page.data.errorDiagnosis ? Number(page.data.errorDiagnosis.id || 0) || undefined : undefined
const localDiagnosisRaw = Object.assign(
{},
responseDiagnosis && raw && raw.diagnosis ? raw.diagnosis : (responseDiagnosis ? raw : {}),
{
  id: responseId || currentId,
  primary_type: primaryType,
  secondary_types: secondaryTypes,
  user_confirmed: true,
  effective_source: 'user',
}
)
const normalized = ports.errorDiagnosis.normalizeDiagnosis(localDiagnosisRaw)
const wq = Object.assign({}, page.data.wq || {}, {
error_type: normalized ? normalized.primaryType : primaryType,
error_diagnosis: localDiagnosisRaw,
})
if (page._wqCache && page._wqCache[wqId]) page._wqCache[wqId] = { data: wq, ts: Date.now() }
page.setData({
wq,
errorDiagnosis: normalized,
nextErrorAction: ports.errorDiagnosis.buildNextAction(wq, normalized),
diagnosisSheetVisible: false,
diagnosisSaving: false,
})
ports.platform.showToast({ title: '错因已记录', icon: 'success' })
} catch (e) {
page.setData({ diagnosisSaving: false })
ports.platform.showToast({ title: ports.requestClient.getErrorMessage(e) || '保存失败', icon: 'none' })
}
}

function openNextErrorAction(page, ports) {
const action = page.data.nextErrorAction
if (!action) return
if (action.route === 'diagnosis') {
page.openDiagnosisSheet()
return
}
if (action.route === 'review_today') {
ports.platform.navigateTo({ url: '/subpackages/study/review-today/review-today' })
return
}
if (action.route === 'exam_list') {
ports.platform.navigateTo({ url: '/subpackages/exam/paper-list/index' })
return
}
const params = action.routeParams && typeof action.routeParams === 'object' ? action.routeParams : {}
const query = Object.keys(params)
.filter(key => params[key] !== undefined && params[key] !== null && params[key] !== '')
.map(key => `${encodeURIComponent(key)}=${encodeURIComponent(String(params[key]))}`)
.join('&')
if (action.route === 'knowledge_detail') {
ports.platform.navigateTo({ url: `/subpackages/knowledge/knowledge-detail/index${query ? '?' + query : ''}` })
return
}
if (action.route === 'knowledge_subject') {
ports.platform.navigateTo({ url: `/subpackages/knowledge/knowledge-subject/index${query ? '?' + query : ''}` })
return
}
if (action.route === 'practice') {
ports.platform.navigateTo({ url: `/subpackages/study/practice/practice${query ? '?' + query : ''}` })
}
}

async function _refreshDiagnosisFromServer(page, wqId, fallbackRaw, ports) {
const id = Number(wqId)
if (!id) return
const requestSeq = ++page._diagnosisRequestSeq
const fallback = ports.errorDiagnosis.normalizeDiagnosis(fallbackRaw)
if (fallback && id === Number(page._currentWqId)) {
const currentWq = Object.assign({}, page.data.wq || {}, { error_diagnosis: fallbackRaw })
page.setData({
wq: currentWq,
errorDiagnosis: fallback,
nextErrorAction: ports.errorDiagnosis.buildNextAction(currentWq, fallback),
})
}
page.setData({ diagnosisSyncing: true })
try {
const raw = await ports.requestClient.get(`/wrong-questions/${id}/diagnosis`, {}, { suppressNetworkToast: true })
if (requestSeq !== page._diagnosisRequestSeq || !page._alive || id !== Number(page._currentWqId)) return
const normalized = ports.errorDiagnosis.normalizeDiagnosis(raw)
if (!normalized) return
// Never let a lagging/empty aggregate overwrite a locally embedded confirmed
// diagnosis. The dedicated endpoint may trail the PUT response briefly.
if (fallback && fallback.userConfirmed && (!normalized.userConfirmed || normalized.primaryType === 'unknown')) return
const currentWq = Object.assign({}, page.data.wq || {}, { error_diagnosis: raw })
if (page._wqCache && page._wqCache[id]) {
page._wqCache[id] = { data: Object.assign({}, page._wqCache[id].data || {}, { error_diagnosis: raw }), ts: Date.now() }
}
page.setData({
wq: currentWq,
errorDiagnosis: normalized,
nextErrorAction: ports.errorDiagnosis.buildNextAction(currentWq, normalized),
})
} catch (e) {
// The detail endpoint is the source of truth when available. A missing record
// simply means no cause has been saved yet; keep the embedded fallback.
} finally {
if (requestSeq === page._diagnosisRequestSeq && page._alive) page.setData({ diagnosisSyncing: false })
}
}

module.exports = { openDiagnosisSheet, closeDiagnosisSheet, selectDiagnosisPrimary, toggleDiagnosisSecondary, saveDiagnosis, openNextErrorAction, _refreshDiagnosisFromServer }

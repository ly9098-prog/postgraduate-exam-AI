// Pure controller for batch diagnosis. Extracted from
// subpackages/study/practice-result/index.js applyBatchDiagnosis.

function createBatchDiagnosisController(options) {
  return {
    apply: applyImpl.bind(null, options),
  }
}

async function applyImpl(options) {
  if (options.getBatchDiagnosisSaving()) return
  const selectedIds = getSelectedIds(options)
  if (!selectedIds.length) {
    options.showToast({ title: '请先选择错题', icon: 'none' })
    return
  }
  const picked = await pickDiagnosisType(options, selectedIds.length)
  if (!picked) return
  options.incrementDiagnosisRefreshSeq()
  options.setData({ batchDiagnosisSaving: true })
  const results = await runBatchRequests(options, selectedIds, picked)
  if (!options.isPageAlive()) return
  commitBatchResults(options, results, picked)
}

function getSelectedIds(options) {
  return Object.keys(options.getBatchSelectedMap() || {})
    .filter(key => options.getBatchSelectedMap()[key])
    .map(Number)
    .filter(id => Number.isFinite(id) && id > 0)
}

async function pickDiagnosisType(options, count) {
  const types = options.getQuickTypes()
  const index = await options.showOptions({
    title: `为 ${count} 道错题设置错因`,
    items: types.map(item => item.label),
  })
  return types[index]
}

async function runBatchRequests(options, selectedIds, picked) {
  const byId = buildByIdMap(options)
  return Promise.all(selectedIds.map(async (wqId) => {
    const target = byId[wqId] || null
    try {
      const raw = await options.putDiagnosis(wqId, buildDiagnosisPayload(target, picked))
      return { wqId, ok: true, diagnosis: options.normalizeDiagnosis(raw) }
    } catch (error) {
      return { wqId, ok: false, error }
    }
  }))
}

function buildByIdMap(options) {
  const byId = {}
  ;(options.getWrongReviewItems() || []).forEach(item => {
    const id = Number(item.wrongQuestionId || 0)
    if (id > 0) byId[id] = item
  })
  return byId
}

function buildDiagnosisPayload(target, picked) {
  return {
    diagnosis_id: target && target.errorDiagnosis ? Number(target.errorDiagnosis.id || 0) || undefined : undefined,
    primary_type: picked.type,
    secondary_types: [],
  }
}

function commitBatchResults(options, results, picked) {
  const succeeded = results.filter(item => item.ok)
  const successMap = {}
  succeeded.forEach(item => { successMap[item.wqId] = item.diagnosis })
  const update = list => (list || []).map(item => {
    const id = Number(item.wrongQuestionId || 0)
    if (!successMap[id]) return item
    return Object.assign({}, item, {
      errorDiagnosis: successMap[id],
      errorDiagnosisLabel: picked.label,
    })
  })
  const failedCount = results.length - succeeded.length
  options.setData({
    reviewItems: update(options.getReviewItems()),
    filteredReviewItems: update(options.getFilteredReviewItems()),
    wrongReviewItems: update(options.getWrongReviewItems()),
    batchDiagnosisSaving: false,
    batchDiagnosisMode: failedCount > 0,
    batchSelectedMap: failedCount > 0
      ? results.reduce((map, item) => { if (!item.ok) map[item.wqId] = true; return map; }, {})
      : {},
    batchSelectedCount: failedCount,
  })
  if (!failedCount) options.showToast({ title: `已标记 ${succeeded.length} 题`, icon: 'success' })
  else options.showToast({ title: `成功 ${succeeded.length} 题，${failedCount} 题失败`, icon: 'none' })
}

module.exports = {
  createBatchDiagnosisController,
}

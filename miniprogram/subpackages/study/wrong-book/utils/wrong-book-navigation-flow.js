async function _checkExportCapability(pageContext, { settings, exportClient }) {
const requestId = ++pageContext._exportCapabilityRequestId
pageContext.setData({
exportAvailable: false,
exportCapabilityChecked: false,
exportUnavailableText: '当前导出功能不可用',
})
if (settings.WRONG_BOOK_EXPORT_ENABLED !== true) {
pageContext.setData({
exportCapabilityChecked: true,
exportUnavailableText: '当前导出功能不可用',
})
return
}
try {
const capability = await exportClient.getCapabilities()
if (requestId !== pageContext._exportCapabilityRequestId) return
const available = !!(
capability &&
capability.export_enabled === true &&
capability.pdf_enabled === true
)
pageContext.setData({
exportAvailable: available,
exportCapabilityChecked: true,
exportUnavailableText: available
? ''
: exportClient.getExportCapabilityErrorMessage(null, capability),
})
} catch (error) {
if (requestId !== pageContext._exportCapabilityRequestId) return
pageContext.setData({
exportAvailable: false,
exportCapabilityChecked: true,
exportUnavailableText: exportClient.getExportCapabilityErrorMessage(error),
})
}
}

function goBack({ getPlatform }) {
getPlatform().navigateBack({ fail: () => getPlatform().reLaunch({ url: '/pages/home/home' }) })
}

function _navigateToDetail(pageContext, id, { getPlatform }) {
const ids = pageContext.data.activeView === 'task'
? pageContext._getVisibleIds()
: (pageContext.data.list || []).map(item => item.id)
if (!ids.some(itemId => String(itemId) === String(id))) ids.unshift(id)
const idx = ids.findIndex(itemId => String(itemId) === String(id))
try {
getPlatform().setStorageSync('wrong_detail_nav', { ids, ts: Date.now() })
} catch (e) {
console.warn('保存错题详情导航上下文失败', e)
}
getPlatform().navigateTo({ url: `/subpackages/study/wrong-detail/wrong-detail?id=${encodeURIComponent(id)}&idx=${Math.max(0, idx)}&source=wrong-book` })
}

function onExportSelected(pageContext, { getPlatform, getApplication }) {
if (!pageContext.data.exportAvailable) {
getPlatform().showToast({
title: pageContext.data.exportUnavailableText || '当前导出功能不可用',
icon: 'none',
})
return
}
const ids = (pageContext.data.selectedIds || []).map(id => {
const n = Number(id)
return Number.isFinite(n) ? n : null
}).filter(Boolean)
if (!ids.length) {
getPlatform().showToast({ title: '请先选择错题', icon: 'none' })
return
}
if (ids.length > 100) {
getPlatform().showToast({ title: '单次最多选择 100 道，请调整筛选条件后重试。', icon: 'none' })
return
}
const app = getApplication()
const gd = app.getGlobalData()
gd.exportSelectedIds = ids
getPlatform().navigateTo({ url: '/subpackages/export/export-config/export-config' })
}

function onViewExportRecords({ getPlatform }) {
getPlatform().navigateTo({ url: '/subpackages/export/export-records/export-records' })
}

function goDetail(pageContext, e) {
pageContext._navigateToDetail(e.currentTarget.dataset.id)
}

module.exports = { _checkExportCapability, goBack, _navigateToDetail, onExportSelected, onViewExportRecords, goDetail }

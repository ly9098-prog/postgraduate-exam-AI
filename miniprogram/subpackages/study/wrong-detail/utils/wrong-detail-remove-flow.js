function openMoreMenu(page) {
page.setData({ moreMenuVisible: true })
}

function closeMoreMenu(page) {
page.setData({ moreMenuVisible: false })
}

function openRemoveConfirm(page) {
page.setData({ moreMenuVisible: false, removeConfirmVisible: true })
}

function closeRemoveConfirm(page) {
if (page.data.removeSubmitting) return
page.setData({ removeConfirmVisible: false })
}

async function removeFromWrongBook(page, deps) {
const wqId = page._currentWqId || (page.data.wq && page.data.wq.id)
if (!wqId || page.data.removeSubmitting) return
page._clearMasterUndo()
page.setData({ removeSubmitting: true })
try {
await deps.requestClient.post('/wrong-questions/batch', {
action: 'remove_from_book',
ids: [wqId],
})
if (!page._alive) return
const oldIds = page.data.questionIds || []
const currentIdx = page.data.currentIdx
const nextIds = oldIds.filter(id => String(id) !== String(wqId))
if (page._wqCache) delete page._wqCache[wqId]
try {
deps.platform.setStorageSync('wrong_detail_nav', { ids: nextIds, ts: Date.now() })
} catch (_) {}
page.setData({
questionIds: nextIds,
totalQuestions: nextIds.length,
removeConfirmVisible: false,
removeSubmitting: false,
})
if (!nextIds.length) {
deps.platform.showToast({ title: '已移出错题本', icon: 'none' })
if (page._removeBackTimer) clearTimeout(page._removeBackTimer)
page._removeBackTimer = setTimeout(() => {
page._removeBackTimer = null
if (page._alive) page.goBack()
}, 220)
return
}
const nextIdx = Math.min(currentIdx, nextIds.length - 1)
page.setData({ currentIdx: nextIdx })
await page.loadData(nextIds[nextIdx])
deps.platform.showToast({ title: '已移出错题本', icon: 'none' })
} catch (e) {
if (!page._alive) return
console.error('移出错题本失败', e)
page.setData({ removeSubmitting: false })
deps.platform.showToast({ title: '移出失败，请重试', icon: 'none' })
}
}

module.exports = { openMoreMenu, closeMoreMenu, openRemoveConfirm, closeRemoveConfirm, removeFromWrongBook }

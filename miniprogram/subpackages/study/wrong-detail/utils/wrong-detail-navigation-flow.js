function _dropQuestionFromNavigation(page, wqId, { writeNavigation }) {
const currentId = page._currentWqId || (page.data.wq && page.data.wq.id)
const oldIds = page.data.questionIds || []
const nextIds = oldIds.filter(id => String(id) !== String(wqId))
if (nextIds.length === oldIds.length) return false
if (page._wqCache) delete page._wqCache[wqId]
try {
writeNavigation({ ids: nextIds, ts: Date.now() })
} catch (_) {}
let nextCurrentIdx = nextIds.findIndex(id => String(id) === String(currentId))
if (nextCurrentIdx < 0) nextCurrentIdx = 0
const wrongQuestions = nextIds.map(() => ({ _answered: true }))
page.setData({
questionIds: nextIds,
totalQuestions: nextIds.length,
currentIdx: nextCurrentIdx,
wrongQuestions,
runnerProgressPercent: nextIds.length > 0
? Math.round((nextCurrentIdx + 1) / nextIds.length * 100)
: 0,
})
return true
}

async function _navigateTo(page, idx, animMs, direction) {
    var navigationSeq = ++page._navigationSeq
    var switchDirection = direction || (idx > page.data.currentIdx ? 'right' : 'left')
    page._switching = true
    page._cancelContentSwitchTransition()
    page._contentTransitionDirection = switchDirection
    page._contentTransitionStartedAt = Date.now()
    page.setData({ showSwitchMask: true })
    try {
      const ctx = await page._prepareNavigationData(idx, navigationSeq)
      if (!ctx) return
      await page._commitNavigation(ctx, switchDirection, animMs, navigationSeq)
    } catch (e) {
      page._handleNavigateError(e, navigationSeq)
    }
  }

async function _commitNavigation(page, ctx, switchDirection, animMs, navigationSeq, { QUESTION_SWITCH_ANIM_WATCHDOG_MS }) {
    const { wqId, wq, raw, nextData, nextAiResult } = ctx
    await page._waitForContentSwitchOut(switchDirection, animMs)
    if (!page._alive || navigationSeq !== page._navigationSeq) return
    page._currentWqId = wqId
    page._errorTypeLabelText = raw.errorTypeLabelText
    page._aiResult = nextAiResult
    clearTimeout(page._switchMaskTimer)
    page._armSwitchWatchdog(QUESTION_SWITCH_ANIM_WATCHDOG_MS)
    page.setData(Object.assign({ showSwitchMask: false }, nextData), () => {
      page._finishContentSwitchTransition(switchDirection)
      page._refreshDiagnosisFromServer(wqId, wq.error_diagnosis)
    })
    page._checkRenderInvariant(raw._renderModel)
  }

function _handleNavigateError(page, e, navigationSeq, { showToast }) {
    if (!page._alive || navigationSeq !== page._navigationSeq) return
    console.error('切换题目失败', e)
    clearTimeout(page._switchMaskTimer)
    page._switching = false
    page._clearSwitchWatchdog()
    page._cancelContentSwitchTransition()
    const statusCode = Number(e && (e.statusCode || e.status)) || 0
    if (statusCode === 404 || statusCode === 410) {
      page._dropQuestionFromNavigation(0)
      page.setData({ showSwitchMask: false, aiRegenerating: false })
      showToast({ title: '该错题已被移除，已更新题目列表', icon: 'none' })
      return
    }
    showToast({ title: '加载失败', icon: 'none' })
    page.setData({ showSwitchMask: false, aiRegenerating: false })
  }

module.exports = { _dropQuestionFromNavigation, _navigateTo, _commitNavigation, _handleNavigateError }

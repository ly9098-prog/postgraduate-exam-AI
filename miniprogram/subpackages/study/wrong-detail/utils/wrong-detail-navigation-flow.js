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
    const ids = page.data.questionIds || []
    if (!page._alive || page._switching || !Number.isInteger(idx) ||
      idx < 0 || idx >= ids.length || idx === page.data.currentIdx || !Number(ids[idx])) return
    var navigationSeq = ++page._navigationSeq
    var switchDirection = direction || (idx > page.data.currentIdx ? 'left' : 'right')
    page._switching = true
    page._pendingNavigationWqId = Number(ids[idx])
    page._cancelContentSwitchTransition()
    page._armSwitchWatchdog()
    clearTimeout(page._switchMaskTimer)
    page._switchMaskTimer = setTimeout(() => {
      if (page._alive && navigationSeq === page._navigationSeq && page._switching) {
        page.setData({ showSwitchMask: true })
      }
    }, 350)
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
    if (!page._alive || navigationSeq !== page._navigationSeq) return
    clearTimeout(page._switchMaskTimer)
    page._switchMaskTimer = null
    if (page.data.showSwitchMask) page.setData({ showSwitchMask: false })
    await page._waitForContentSwitchOut(switchDirection, animMs)
    if (!page._alive || navigationSeq !== page._navigationSeq) return
    page._currentWqId = wqId
    page._errorTypeLabelText = raw.errorTypeLabelText
    page._aiResult = nextAiResult
    page._aiRequestId = Number(page._aiRequestId || 0) + 1
    page._teacherRequestSeq = Number(page._teacherRequestSeq || 0) + 1
    page._diagnosisRequestSeq = Number(page._diagnosisRequestSeq || 0) + 1
    page._aiGenerationMarker = String(wq.ai_analysis_generated_at || '')
    page._activeTeacherCacheKey = ''
    page._pendingNavigationWqId = null
    page._armSwitchWatchdog(QUESTION_SWITCH_ANIM_WATCHDOG_MS)
    page.setData(Object.assign({ showSwitchMask: false }, nextData), () => {
      if (!page._alive || navigationSeq !== page._navigationSeq) return
      page._finishContentSwitchTransition(switchDirection)
      page._refreshDiagnosisFromServer(wqId, wq.error_diagnosis)
      page._prefetchWrongQuestion(page.data.currentIdx - 1)
      page._prefetchWrongQuestion(page.data.currentIdx + 1)
    })
    page._checkRenderInvariant(raw._renderModel)
  }

function _handleNavigateError(page, e, navigationSeq, { showToast }) {
    if (!page._alive || navigationSeq !== page._navigationSeq) return
    console.error('切换题目失败', e)
    clearTimeout(page._switchMaskTimer)
    page._switchMaskTimer = null
    page._switching = false
    page._clearSwitchWatchdog()
    page._cancelContentSwitchTransition()
    const statusCode = Number(e && (e.statusCode || e.status)) || 0
    if (statusCode === 404 || statusCode === 410) {
      page._dropQuestionFromNavigation(page._pendingNavigationWqId)
      page._pendingNavigationWqId = null
      page.setData({ showSwitchMask: false, aiRegenerating: false })
      showToast({ title: '该错题已被移除，已更新题目列表', icon: 'none' })
      return
    }
    showToast({ title: '加载失败', icon: 'none' })
    page.setData({ showSwitchMask: false, aiRegenerating: false })
  }

module.exports = { _dropQuestionFromNavigation, _navigateTo, _commitNavigation, _handleNavigateError }

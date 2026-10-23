function createReviewMasterController(options) {
  return {
    tap(event) {
      if (options.isMasterSubmitting() || options.isSubmittingGroup() || options.isMasterUndoInFlight()) return
      const question = event && event.detail && event.detail.question
      const scheduleId = question && question.schedule_id
      if (!scheduleId) return
      options.setData({ masterConfirmId: scheduleId })
    },

    cancel() {
      if (options.isMasterSubmitting()) return
      options.setData({ masterConfirmId: null })
    },

    async confirm() {
      return confirmMaster(options)
    },

    async undo() {
      return undoMaster(options)
    },

    armUndoExpiry(ms) {
      armUndoExpiry(options, ms)
    },

    clearUndo() {
      clearUndo(options)
    },
  }
}

async function confirmMaster(options) {
  if (options.isMasterSubmitting() || options.isSubmittingGroup()) return
  const plan = buildMasterPlan(options)
  if (!plan) return
  options.setData({ masterSubmitting: true })
  if (!await options.syncReviewSessionDay()) {
    if (options.isPageAlive()) options.setData({ masterSubmitting: false, masterConfirmId: null })
    return
  }
  try {
    const masterResult = await options.postMaster(plan.scheduleId)
    if (!options.isPageAlive()) return
    const serverTaskActive = !(masterResult && masterResult.active === false)
    const changedByThisRequest = serverTaskActive && !(masterResult && masterResult.changed === false)
    await options.refreshOverviewStatsSilently()
    if (!options.isPageAlive()) return
    options.clearUndo()
    if (changedByThisRequest) options.setPendingMasterUndo(buildPendingUndo(options, plan))
    applyMasterRemoval(options, plan, { serverTaskActive, changedByThisRequest })
  } catch (error) {
    handleMasterError(options, error)
  }
}

function buildMasterPlan(options) {
  const data = options.getData()
  const currentGroupSnapshot = (data.groupQuestions || []).slice()
  const scheduleId = data.masterConfirmId
  const question = currentGroupSnapshot.find(q => String(q.schedule_id) === String(scheduleId))
  const originalIndex = currentGroupSnapshot.findIndex(q => String(q.schedule_id) === String(scheduleId))
  const originalGroupIdx = Number(data.currentGroupIdx || 0)
  const groupsBeforeMaster = (data.groups || []).map(group => Array.isArray(group) ? group.slice() : [])
  if (!scheduleId || !question || originalIndex < 0) return null
  return {
    scheduleId,
    question,
    originalIndex,
    originalGroupIdx,
    groupsBeforeMaster,
    currentGroupSnapshot,
    currentIndex: Number(data.currentIndex || 0),
  }
}

function buildPendingUndo(options, plan) {
  return {
    scheduleId: plan.scheduleId,
    question: plan.question,
    originalAnswer: options.getSession().answers[plan.scheduleId],
    originalIndex: Math.max(0, plan.originalIndex),
    originalGroupIdx: plan.originalGroupIdx,
    groupsBeforeMaster: plan.groupsBeforeMaster,
  }
}

function applyMasterRemoval(options, plan, outcome) {
  const groupQuestions = plan.currentGroupSnapshot.filter(q => String(q.schedule_id) !== String(plan.scheduleId))
  const groupState = buildGroupsAfterMaster(plan, groupQuestions)
  const session = options.getSession()
  const answers = { ...session.answers }
  delete answers[plan.scheduleId]
  session.answers = answers
  if (outcome.changedByThisRequest) options.incrementMasteredCount()
  session.allQuestions = groupQuestions.slice()
  options.setData({
    masterConfirmId: null,
    masterSubmitting: false,
    groups: groupState.groups,
    currentGroupIdx: groupState.safeGroupIdx,
    groupQuestions,
    masterUndoVisible: outcome.changedByThisRequest,
    masterUndoText: outcome.changedByThisRequest ? '已标记掌握，不再进入复习计划' : '',
  })
  if (outcome.changedByThisRequest) {
    options.armUndoExpiry(5000)
  } else {
    options.showToast({
      title: outcome.serverTaskActive ? '题目状态已同步' : '该题已移出复习计划',
      icon: 'none',
    })
  }
  finishMasterRemoval(options, groupQuestions, plan.currentIndex)
}

function buildGroupsAfterMaster(plan, groupQuestions) {
  const groups = plan.groupsBeforeMaster.length > 0
    ? plan.groupsBeforeMaster.map(group => group.slice())
    : [plan.currentGroupSnapshot.slice()]
  let safeGroupIdx = plan.originalGroupIdx
  if (safeGroupIdx < 0 || safeGroupIdx >= groups.length) safeGroupIdx = 0
  if (!groups.length) groups.push(groupQuestions.slice())
  else groups[safeGroupIdx] = groupQuestions.slice()
  return { groups, safeGroupIdx }
}

function finishMasterRemoval(options, groupQuestions, currentIndex) {
  if (groupQuestions.length === 0) {
    options.clearReviewTimer()
    const nextPhase = options.getTodayRemainingCount() > 0 ? 'overview' : 'empty'
    options.setData({
      phase: nextPhase,
      groupQuestions: [],
      currentQuestion: null,
      currentIndex: 0,
    })
    return
  }
  let safeCurrentIndex = currentIndex
  if (safeCurrentIndex >= groupQuestions.length) {
    safeCurrentIndex = Math.max(0, groupQuestions.length - 1)
  }
  options.setData({ currentIndex: safeCurrentIndex })
  options.syncAnsweredFlags()
  options.showQuestion(safeCurrentIndex)
}

async function undoMaster(options) {
  const pending = options.getPendingMasterUndo()
  if (!pending || options.isMasterUndoInFlight() || options.isMasterSubmitting()) return
  options.setMasterUndoInFlight(true)
  clearUndoTimer(options)
  try {
    if (!await options.syncReviewSessionDay()) {
      if (options.isPageAlive() && options.getPendingMasterUndo() === pending) {
        options.setData({ masterUndoVisible: true })
        options.armUndoExpiry(5000)
      }
      return
    }
    const unmasterResult = await options.postUnmaster(pending.scheduleId)
    if (!options.isPageAlive()) return
    if (unmasterResult && unmasterResult.active === false) {
      options.clearUndo()
      await options.refreshOverviewStatsSilently()
      if (options.isPageAlive()) {
        options.showToast({ title: '该题已移出复习计划，无法撤销', icon: 'none' })
      }
      return
    }
    applyMasterUndo(options, pending, unmasterResult)
    await options.refreshOverviewStatsSilently()
    if (!options.isPageAlive()) return
    options.showToast({ title: '已撤销掌握', icon: 'none' })
  } catch (error) {
    handleUndoError(options, pending, error)
  } finally {
    options.setMasterUndoInFlight(false)
  }
}

function applyMasterUndo(options, pending, unmasterResult) {
  const restoredQuestion = {
    ...pending.question,
    occurrence_seq: unmasterResult && unmasterResult.occurrence_seq != null
      ? unmasterResult.occurrence_seq
      : pending.question.occurrence_seq,
  }
  const restoreState = buildRestoreState(options, pending, restoredQuestion)
  const session = options.getSession()
  const restoredAnswers = { ...session.answers }
  if (pending.originalAnswer !== undefined) {
    restoredAnswers[pending.scheduleId] = pending.originalAnswer
  }
  session.answers = restoredAnswers
  session.allQuestions = restoreState.restoredGroup.slice()
  options.decrementMasteredCount()
  options.clearUndo()
  const restoredIndex = Math.min(restoreState.targetIndex, Math.max(0, restoreState.restoredGroup.length - 1))
  options.setData({
    phase: 'reviewing',
    groups: restoreState.restoredGroups,
    currentGroupIdx: restoreState.restoredGroupIdx,
    groupQuestions: restoreState.restoredGroup,
    currentIndex: restoredIndex,
    masterUndoVisible: false,
  })
  options.syncAnsweredFlags()
  if (restoreState.restoredGroup.length > 0) {
    options.showQuestion(restoredIndex)
    options.startReviewTimer()
  }
}

function buildRestoreState(options, pending, restoredQuestion) {
  let restoredGroups = Array.isArray(pending.groupsBeforeMaster)
    ? pending.groupsBeforeMaster.map(group => Array.isArray(group) ? group.slice() : [])
    : []
  let restoredGroupIdx = Number(pending.originalGroupIdx || 0)
  if (!restoredGroups.length) {
    restoredGroups = [(options.getSession().allQuestions || []).slice()]
    restoredGroupIdx = 0
  }
  if (restoredGroupIdx < 0 || restoredGroupIdx >= restoredGroups.length) restoredGroupIdx = 0
  const restoredGroup = restoredGroups[restoredGroupIdx].slice()
  let targetIndex = restoredGroup.findIndex(q => String(q.schedule_id) === String(pending.scheduleId))
  if (targetIndex >= 0) {
    restoredGroup[targetIndex] = restoredQuestion
  } else {
    targetIndex = Math.min(Math.max(0, Number(pending.originalIndex || 0)), restoredGroup.length)
    restoredGroup.splice(targetIndex, 0, restoredQuestion)
  }
  restoredGroups[restoredGroupIdx] = restoredGroup
  return { restoredGroups, restoredGroupIdx, restoredGroup, targetIndex }
}

function armUndoExpiry(options, ms) {
  const timer = options.getMasterUndoTimer()
  if (timer) options.clearTimeout(timer)
  const duration = Number(ms) > 0 ? Number(ms) : 5000
  options.setMasterUndoTimer(options.setTimeout(() => {
    options.setPendingMasterUndo(null)
    options.setMasterUndoTimer(null)
    if (options.isPageAlive()) options.setData({ masterUndoVisible: false })
  }, duration))
}

function clearUndoTimer(options) {
  const timer = options.getMasterUndoTimer()
  if (timer) {
    options.clearTimeout(timer)
    options.setMasterUndoTimer(null)
  }
}

function clearUndo(options) {
  clearUndoTimer(options)
  options.setPendingMasterUndo(null)
  const data = options.getData()
  if (options.isPageAlive() && data && data.masterUndoVisible) {
    options.setData({ masterUndoVisible: false })
  }
}

function handleMasterError(options, error) {
  if (!options.isPageAlive()) return
  options.logError('标记掌握失败', error)
  options.setData({ masterSubmitting: false, masterConfirmId: null })
  options.showToast({ title: '操作失败，请重试', icon: 'none' })
}

function handleUndoError(options, pending, error) {
  if (!options.isPageAlive()) return
  options.logError('撤销掌握失败', error)
  if (options.getPendingMasterUndo() === pending) {
    options.setData({ masterUndoVisible: true })
    options.armUndoExpiry(5000)
  }
  options.showToast({ title: '撤销失败，请重试', icon: 'none' })
}

module.exports = {
  createReviewMasterController,
}

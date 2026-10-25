function createPaperCancelResumeController(options) {
  return {
    cancel: cancelImpl.bind(null, options),
  }
}

async function cancelImpl(options, event) {
  const paperId = Number(event.currentTarget.dataset.id)
  const attemptId = Number(event.currentTarget.dataset.attemptId)
  if (!paperId || !attemptId || options.getStartingId() || options.getCancellingAttemptId()) {
    return
  }

  const paper = options.findPaper(paperId)
  if (!paper || !paper.canResume || Number(paper.latest_attempt_id) !== attemptId) {
    await options.refreshAfterStateMismatch()
    return
  }

  const confirmed = await options.confirmCancel()
  if (!confirmed || !options.isPageAlive()) return

  options.setCancellingAttemptId(attemptId)
  try {
    const result = await options.abandonAttempt(attemptId)
    if (!result || result.status !== 'abandoned' || Number(result.id) !== attemptId) {
      throw new Error('INVALID_ABANDON_RESPONSE')
    }

    // Only clear local drafts after the server has durably accepted the
    // cancellation. A network failure must leave the cache intact so the
    // user can still resume safely.
    options.clearAttemptCache(attemptId)
    if (!options.isPageAlive()) return
    options.optimisticallyClearResume(paperId, attemptId)
    options.showToast({ title: '已取消本次作答', icon: 'success' })

    // Reconcile with the server after the optimistic update. force=true is
    // important when an older onShow request is still running.
    await options.refreshAfterCancel()
  } catch (error) {
    if (!options.isPageAlive()) return
    await handleCancelError(options, error, attemptId)
  } finally {
    if (options.isPageAlive() && Number(options.getCancellingAttemptId()) === attemptId) {
      options.setCancellingAttemptId(0)
    }
  }
}

async function handleCancelError(options, error, attemptId) {
  // A 409 means another request/device won a terminal-state race, or the
  // countdown has just elapsed. Confirm the real attempt state before
  // touching local drafts: list_papers may *present* an elapsed in_progress
  // row as expired even though its pending answers still need atomic submit.
  if (Number(error && error.statusCode) === 409) {
    await options.reconcileAttemptCache(attemptId)
    await options.refreshAfterCancel()
    options.showToast({ title: '作答状态已变化，请重新确认', icon: 'none' })
    return
  }
  options.showToast({ title: options.getErrorMessage(error), icon: 'none' })
}

module.exports = {
  createPaperCancelResumeController,
}

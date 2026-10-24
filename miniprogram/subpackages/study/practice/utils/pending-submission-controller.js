function createPendingSubmissionController(options) {
  return {
    read: readImpl.bind(null, options),
    persist: persistImpl.bind(null, options),
    clear: clearImpl.bind(null, options),
    offerRecovery: offerRecoveryImpl.bind(null, options),
  }
}

function readImpl(options) {
  const key = options.getStorageKey()
  if (!key) return null
  try {
    const item = options.readStorage(key)
    if (!item || item.version !== 1 || !item.submission) return null
    const createdAt = Number(item.createdAt) || 0
    const freshnessAt = Number(item.updatedAt) || createdAt
    if (!freshnessAt || options.now() - freshnessAt > options.getTtlMs()) {
      options.removeStorage(key)
      return null
    }
    return item
  } catch (_) {
    return null
  }
}

function persistImpl(options, submission, status, resultUrl) {
  const key = options.getStorageKey()
  if (!key || !submission) return false
  const previousPersisted = !!submission.pendingPersisted
  try {
    const previous = options.readStorage(key)
    const createdAt = previous && previous.submission && previous.submission.requestId === submission.requestId
      ? (Number(previous.createdAt) || options.now())
      : options.now()
    submission.pendingPersisted = true
    options.writeStorage(key, {
      version: 1,
      createdAt,
      updatedAt: options.now(),
      status: status || 'pending',
      resultUrl: resultUrl || '',
      submission,
    })
    return true
  } catch (error) {
    submission.pendingPersisted = previousPersisted
    options.logWarn('保存待确认交卷失败', error)
    return false
  }
}

function clearImpl(options, requestId) {
  const key = options.getStorageKey()
  if (!key) return
  try {
    const item = options.readStorage(key)
    if (!requestId || !item || !item.submission || item.submission.requestId === requestId) {
      options.removeStorage(key)
    }
  } catch (_) {}
}

async function offerRecoveryImpl(options) {
  const pending = readImpl(options)
  if (!pending || !options.isPageAlive()) return false
  const submission = pending.submission

  if (pending.status === 'submitted' && pending.resultUrl) {
    const confirmed = await options.showConfirm({
      scenario: 'info',
      title: '上次练习已交卷',
      message: '结果页尚未确认打开，是否继续查看？',
      confirmText: '查看结果',
      cancelText: '稍后处理',
      hideEyebrow: true,
    })
    if (confirmed && options.isPageAlive()) {
      options.restoreSubmittedSnapshot(submission, pending.resultUrl)
      return true
    }
    return false
  }

  if (pending.status === 'blocked' || submission.retryBlocked) {
    const confirmed = await options.showConfirm({
      scenario: 'danger',
      title: '上次交卷无法继续确认',
      message: '该提交已被服务器拒绝。清除本地状态后即可重新开始。',
      confirmText: '清除状态',
      cancelText: '暂不处理',
      hideEyebrow: true,
    })
    if (confirmed) clearImpl(options, submission.requestId)
    return false
  }

  const confirmed = await options.showConfirm({
    scenario: 'info',
    title: '发现待确认交卷',
    message: '可继续确认上次交卷，不会重复计入答题记录。',
    confirmText: '继续确认',
    cancelText: '稍后处理',
    hideEyebrow: true,
  })
  if (!confirmed || !options.isPageAlive()) return false
  return options.resumePendingSubmission(submission)
}

module.exports = {
  createPendingSubmissionController,
}

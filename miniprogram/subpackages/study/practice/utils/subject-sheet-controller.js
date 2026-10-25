const SUBJECT_DOUBLE_TAP_INTERVAL = 320

function createSubjectSheetController(options) {
  return {
    open: () => open(options),
    hide: afterClose => hide(options, afterClose),
    handleOptionTap: (subjectId, source) => handleOptionTap(options, subjectId, source),
  }
}

function open(options) {
  const timer = options.getCloseTimer()
  if (timer) options.clearTimeout(timer)
  options.setCloseTimer(null)
  options.setData({ subjectSheetVisible: true, subjectSheetClosing: false })
}

function hide(options, afterClose) {
  if (!options.isVisible()) {
    if (typeof afterClose === 'function') afterClose()
    return
  }
  if (options.isClosing()) return
  const timer = options.getCloseTimer()
  if (timer) options.clearTimeout(timer)
  options.setData({ subjectSheetClosing: true }, () => {
    options.setCloseTimer(options.setTimeout(() => {
      options.setCloseTimer(null)
      if (!options.isPageAlive()) return
      options.setData(
        { subjectSheetVisible: false, subjectSheetClosing: false },
        () => {
          if (typeof afterClose === 'function') afterClose()
        },
      )
    }, 180))
  })
}

function handleOptionTap(options, subjectId, source) {
  const id = Number(subjectId)
  if (!id || !options.isVisible() || options.isClosing()) return
  const now = options.now()
  const key = `${source || 'subject'}:${id}`
  const lastTap = options.getLastTap()
  const isDoubleTap = Boolean(
    lastTap &&
    lastTap.key === key &&
    now - lastTap.time <= SUBJECT_DOUBLE_TAP_INTERVAL,
  )
  options.setLastTap(isDoubleTap ? null : { key, time: now })
  if (isDoubleTap) options.closeSheet()
}

module.exports = {
  createSubjectSheetController,
  SUBJECT_DOUBLE_TAP_INTERVAL,
}

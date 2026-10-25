function createDateRequestController(options) {
  const isCurrent = (seq, checkSelectedDate, requestedDate) =>
    isCurrentImpl(options, seq, checkSelectedDate, requestedDate)
  const fetchEffectiveHistory = (requestDate, effectiveDate, viewingToday, reconciled, initialHistory) =>
    fetchEffectiveHistoryImpl(options, requestDate, effectiveDate, viewingToday, reconciled, initialHistory)
  return {
    load: loadImpl.bind(null, options, isCurrent, fetchEffectiveHistory),
  }
}

function isCurrentImpl(options, seq, checkSelectedDate, requestedDate) {
  return (
    options.isAlive() &&
    options.isVisible() &&
    seq === options.getDateRequestSeq() &&
    (!checkSelectedDate || requestedDate === options.getSelectedDate())
  )
}

async function fetchEffectiveHistoryImpl(options, requestDate, effectiveDate, viewingToday, reconciled, initialHistory) {
  if (!viewingToday || !reconciled.changedToday || effectiveDate === requestDate) {
    return initialHistory
  }
  let effectiveHistory
  try {
    effectiveHistory = await options.getHistory(effectiveDate)
  } catch (error) {
    options.logError('重取今日 history 失败', error)
    effectiveHistory = { items: [], total: 0 }
  }
  return effectiveHistory
}

async function loadImpl(options, isCurrent, fetchEffectiveHistory, date) {
  const requestDate = String(date || '').trim()
  if (!requestDate) return

  options.incrementDateRequestSeq()
  const seq = options.getDateRequestSeq()
  const showDayDistribution = options.getDistributionPeriod() === 'day'
  if (showDayDistribution) options.setData({ pieLoading: true })
  const viewingToday = requestDate === options.getTodayDate()

  try {
    const responses = await options.getInitialResponses(requestDate, viewingToday)
    const summary = responses[0]
    const historyRes = responses[1]
    if (!isCurrent(seq, true, requestDate)) return

    const reconciled = options.reconcileFromServer(null, viewingToday ? summary : null)
    if (!isCurrent(seq, false)) return

    const effectiveDate = options.getSelectedDate()
    const effectiveHistory = await fetchEffectiveHistory(requestDate, effectiveDate, viewingToday, reconciled, historyRes)
    if (!isCurrent(seq, false)) return

    commitDateViewState(options, seq, showDayDistribution, summary, effectiveHistory, effectiveDate)
  } catch (error) {
    options.handleDateFailure(error, { seq })
  }
}

function commitDateViewState(options, seq, showDayDistribution, summary, effectiveHistory, effectiveDate) {
  const viewState = options.buildDateViewState({
    summary,
    effectiveHistory,
    effectiveDate,
    todayDate: options.getTodayDate(),
    showDayDistribution,
  })
  options.setRawTodayDuration(viewState.selectedDurationSec)
  options.setDaySubjectsRaw(viewState.subjectBreakdown)
  if (showDayDistribution) options.resetPieCache()
  options.commitDate(viewState, { seq, showDayDistribution })
}

module.exports = {
  createDateRequestController,
}

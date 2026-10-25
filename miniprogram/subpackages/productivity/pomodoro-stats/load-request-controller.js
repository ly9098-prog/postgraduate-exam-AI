function createLoadRequestController(options) {
  const isCurrent = (reqId, dateSeq, checkSelectedDate, requestedDate) =>
    isCurrentImpl(options, reqId, dateSeq, checkSelectedDate, requestedDate)
  const beginLoad = background => beginLoadImpl(options, background)
  const fetchEffectiveHistory = (requestedDate, effectiveDate, viewingToday, reconciled, initialHistory) =>
    fetchEffectiveHistoryImpl(options, requestedDate, effectiveDate, viewingToday, reconciled, initialHistory)
  return {
    load: loadImpl.bind(null, options, isCurrent, beginLoad, fetchEffectiveHistory),
  }
}

function isCurrentImpl(options, reqId, dateSeq, checkSelectedDate, requestedDate) {
  if (!options.isAlive() || reqId !== options.getRequestId()) return false
  if (dateSeq !== options.getDateRequestSeq()) return false
  return !checkSelectedDate || requestedDate === options.getSelectedDate()
}

async function beginLoadImpl(options, background) {
  await options.ensureSettings()
  const subjectMetaPromise = options.ensureSubjectMeta().catch(() => null)
  if (!options.isAlive()) return null

  const reqId = options.getRequestId()
  const requestedDate = options.getSelectedDate()
  options.incrementDateRequestSeq()
  const dateSeq = options.getDateRequestSeq()
  if (options.hasData()) options.cancelDeferredHistory(true)
  if (!background) options.setData({ loading: true, errorText: '' })
  options.incrementStatsLoadInFlight()
  return {
    subjectMetaPromise,
    reqId,
    requestedDate,
    dateSeq,
    viewingToday: !requestedDate || requestedDate === options.getTodayDate(),
  }
}

async function fetchEffectiveHistoryImpl(options, requestedDate, effectiveDate, viewingToday, reconciled, initialHistory) {
  if (!reconciled.changedToday || !viewingToday || effectiveDate === requestedDate) {
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

async function loadImpl(options, isCurrent, beginLoad, fetchEffectiveHistory, background) {
  const request = await beginLoad(background)
  if (!request) return

  try {
    const normalized = await fetchInitialData(options, request)
    if (!isCurrent(request.reqId, request.dateSeq, true, request.requestedDate)) return

    const reconciled = options.reconcileFromServer(
      normalized.stats,
      request.viewingToday ? normalized.summary : null
    )
    if (!isCurrent(request.reqId, request.dateSeq, false)) return

    const effectiveDate = options.getSelectedDate()
    const authoritativeToday = reconciled.today || options.getTodayDate() || effectiveDate
    const effectiveHistory = await fetchEffectiveHistory(
      request.requestedDate, effectiveDate, request.viewingToday, reconciled, normalized.historyRes
    )
    if (!isCurrent(request.reqId, request.dateSeq, false)) return

    commitViewState(options, request, effectiveDate, effectiveHistory, normalized, authoritativeToday)
  } catch (error) {
    options.handleLoadFailure(error, {
      background,
      reqId: request.reqId,
      dateSeq: request.dateSeq,
      requestedDate: request.requestedDate,
    })
  } finally {
    options.decrementStatsLoadInFlight()
  }
}

async function fetchInitialData(options, request) {
  const responses = await options.getInitialResponses(request.requestedDate, request.viewingToday)
  await request.subjectMetaPromise
  const historyRes = responses[1]
  const normalized = options.normalizeOverview(responses[0])
  return { ...normalized, historyRes }
}

function commitViewState(options, request, effectiveDate, effectiveHistory, normalized, authoritativeToday) {
  const willAnimate = !options.hasData()
  options.setHasData(true)
  options.cancelDurationAnimation(false)
  const displayDaySubjects = options.getDistributionPeriod() === 'day'
  if (displayDaySubjects) options.resetPieCache()
  const viewState = options.buildLoadViewState({
    stats: normalized.stats,
    summary: normalized.summary,
    lifetime: normalized.lifetime,
    trends: normalized.trends,
    effectiveHistory,
    effectiveDate,
    authoritativeToday,
    willAnimate,
    displayDaySubjects,
  })
  options.commitLoad(viewState, {
    reqId: request.reqId,
    dateSeq: request.dateSeq,
    effectiveDate,
    effectiveHistory,
    willAnimate,
    displayDaySubjects,
    weekDurationSec: normalized.stats.week_duration_sec || 0,
  })
}

module.exports = {
  createLoadRequestController,
}

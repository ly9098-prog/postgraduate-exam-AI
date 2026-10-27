const { parseServerUtc } = require('./china-time')
const { getResponseHeader: _getResponseHeader } = require('./api-error')

let _serverClockOffsetMs = 0
let _serverClockSynced = false
let _serverClockSampleAtMs = 0
let _serverClockBestRttMs = Infinity
let _serverClockSourceRank = 0

function _updateServerClock(res, requestStartedAt, responseReceivedAt) {
  if (!res) return
  let serverMs = NaN
  let sourceRank = 0
  if (res.data && typeof res.data === 'object' && res.data.server_now) {
    serverMs = parseServerUtc(res.data.server_now)
    if (Number.isFinite(serverMs)) sourceRank = 2
  }
  if (!Number.isFinite(serverMs)) {
    const dateHeader = _getResponseHeader(res.header, 'Date')
    if (dateHeader) serverMs = Date.parse(dateHeader)
    if (Number.isFinite(serverMs)) sourceRank = 1
  }
  if (!Number.isFinite(serverMs)) return

  const receivedAt = Number.isFinite(responseReceivedAt) ? responseReceivedAt : Date.now()
  const startedAt = Number.isFinite(requestStartedAt) ? requestStartedAt : receivedAt
  const rttMs = Math.max(0, receivedAt - startedAt)
  const clientMidpointMs = startedAt + rttMs / 2
  const candidateOffsetMs = serverMs - clientMidpointMs
  const sampleExpired = !_serverClockSampleAtMs || receivedAt - _serverClockSampleAtMs > 10 * 60 * 1000
  const sourceImproved = sourceRank > _serverClockSourceRank
  const rttImproved = sourceRank === _serverClockSourceRank && rttMs <= _serverClockBestRttMs + 50

  // Prefer explicit server_now and low-RTT samples. Periodically accept a fresh
  // sample even when RTT is worse so a device clock adjustment can self-heal.
  if (!_serverClockSynced || sampleExpired || sourceImproved || rttImproved) {
    _serverClockOffsetMs = candidateOffsetMs
    _serverClockSynced = true
    _serverClockSampleAtMs = receivedAt
    _serverClockBestRttMs = rttMs
    _serverClockSourceRank = sourceRank
  }
}

function now() {
  return Date.now() + (_serverClockSynced ? _serverClockOffsetMs : 0)
}

module.exports = {
  updateServerClock: _updateServerClock,
  now,
}

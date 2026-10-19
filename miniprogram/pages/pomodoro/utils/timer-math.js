// Pure display and elapsed-time rules; clocks and storage belong to the Page.
function formatElapsedSec(sec) {
  const s = Math.max(0, sec || 0)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const secs = s % 60
  return {
    display: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(secs).padStart(2, '0')}`,
    friendly: h > 0
      ? `${h}小时${String(m).padStart(2, '0')}分${String(secs).padStart(2, '0')}秒`
      : m > 0
        ? `${m}分${String(secs).padStart(2, '0')}秒`
        : `${secs}秒`,
  }
}

function formatCountdownDisplay(sec) {
  const safe = Math.max(0, Number(sec) || 0)
  const m = Math.floor(safe / 60)
  const s = safe % 60
  return {
    min: String(m).padStart(2, '0'),
    sec: String(s).padStart(2, '0'),
  }
}

function calculateElapsedMs(now, sessionStartTime, totalPausedMs = 0) {
  const startTime = Number(sessionStartTime)
  if (!Number.isFinite(startTime) || startTime <= 0) return 0
  return Math.max(0, now - startTime - Number(totalPausedMs))
}

module.exports = { formatElapsedSec, formatCountdownDisplay, calculateElapsedMs }

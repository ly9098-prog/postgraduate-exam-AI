function padTwo(value) {
  return String(value).padStart(2, '0')
}

function formatElapsedSec(sec) {
  const s = Math.max(0, sec || 0)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const secs = s % 60
  return {
    display: `${padTwo(h)}:${padTwo(m)}:${padTwo(secs)}`,
    friendly: h > 0
      ? `${h}小时${padTwo(m)}分${padTwo(secs)}秒`
      : m > 0
        ? `${m}分${padTwo(secs)}秒`
        : `${secs}秒`,
  }
}

function formatCountdownDisplay(sec) {
  const safe = Math.max(0, Number(sec) || 0)
  return {
    min: padTwo(Math.floor(safe / 60)),
    sec: padTwo(safe % 60),
  }
}

module.exports = { formatElapsedSec, formatCountdownDisplay }

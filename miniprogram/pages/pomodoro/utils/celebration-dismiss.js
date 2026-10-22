function resolveBreakSec(completionFlag, completionBreakSec, data) {
  if (completionFlag && completionFlag.breakSec !== undefined && Number.isFinite(Number(completionFlag.breakSec))) {
    return Math.max(0, Number(completionFlag.breakSec))
  }
  if (Number.isFinite(completionBreakSec)) {
    return Math.max(0, Number(completionBreakSec))
  }
  return data.selectedPreset === 'debug'
    ? 5
    : Math.max(0, Number(data.breakDuration || 0) * 60)
}

module.exports = { resolveBreakSec }

// Confirm-window snapshots are the durable bridge between the dialog and local
// recovery. Building and validating them stays pure so the page only owns the
// side effects (storage, pending queue, timer mutation) around them.
const CONFIRM_SNAPSHOT_MAX_AGE_MS = 3600000

function isValidConfirmSnapshot(snapshot, nowMs) {
  if (!snapshot || !snapshot.sessionId) return false
  if (!snapshot.mode) return false
  if (snapshot.confirmVisible === false) return false
  if (!snapshot.openedAt) return false
  // Snapshots older than 1 hour are stale.
  if (nowMs - snapshot.openedAt > CONFIRM_SNAPSHOT_MAX_AGE_MS) return false
  return true
}

function buildFreeConfirmSnapshot(input) {
  return {
    mode: 'free-complete',
    confirmActionSeq: input.confirmActionSeq,
    sessionId: input.sessionId,
    openedAt: input.openedAt,
    wasPaused: input.wasPaused,
    pausedByConfirm: !input.wasPaused,
    elapsedSec: input.elapsedSec,
    totalPausedMs: input.totalPausedMs,
    pauseStartTime: input.pauseStartTime,
    sessionStartTime: input.sessionStartTime,
    backendPauseDone: false,
    confirmVisible: true,
    freeDisplayOffsetMs: 0,
  }
}

function buildCountdownInterruptSnapshot(input) {
  return {
    mode: 'countdown-interrupt',
    confirmActionSeq: input.confirmActionSeq,
    sessionId: input.sessionId,
    openedAt: input.openedAt,
    wasPaused: input.wasPaused,
    pausedByConfirm: !input.wasPaused,
    phase: input.phase,
    totalSec: input.totalSec,
    totalMs: input.totalMs,
    remainingMs: input.remainingMs,
    remainingSec: input.remainingSec,
    progress: input.progress,
    sessionStartTime: input.sessionStartTime,
    countdownEndAt: input.countdownEndAt,
    totalPausedMs: input.totalPausedMs,
    pauseStartTime: input.pauseStartTime,
    backendPauseDone: false,
    confirmVisible: true,
  }
}

module.exports = {
  CONFIRM_SNAPSHOT_MAX_AGE_MS,
  isValidConfirmSnapshot,
  buildFreeConfirmSnapshot,
  buildCountdownInterruptSnapshot,
}

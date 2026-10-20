/**
 * Regression checks for Pomodoro lifecycle/network resilience.
 * Usage: node scripts/test-pomodoro-resilience.js
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

let passed = 0
let failed = 0
function t(name, fn) {
  try { fn(); passed++; console.log('  ✓ ' + name) }
  catch (e) { failed++; console.error('  ✗ ' + name + ' - ' + e.message) }
}

const src = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.js'), 'utf8')
const queueSrc = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/utils/pending-sync-queue.js'), 'utf8')
const apiSrc = fs.readFileSync(path.resolve(__dirname, '../utils/api.js'), 'utf8')
const storageSrc = fs.readFileSync(path.resolve(__dirname, '../utils/storage.js'), 'utf8')
const backendServiceSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/app/services/pomodoro_service.py'), 'utf8')
const backendApiSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/app/api/v1/pomodoro.py'), 'utf8')
const backendModelSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/app/models/pomodoro.py'), 'utf8')
const backendSchemaSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/app/schemas/pomodoro.py'), 'utf8')
const backendMigrationSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/alembic/versions/x8y9z0a1b2c3_add_pomodoro_client_start_id.py'), 'utf8')
const backendCorrectiveMigrationSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/alembic/versions/y9z0a1b2c3d4_repair_pomodoro_constraints.py'), 'utf8')
const backendDefinitionMigrationSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/alembic/versions/z0a1b2c3d4e5_verify_pomodoro_constraint_definitions.py'), 'utf8')
const backendPostgresConcurrencyTestSrc = fs.readFileSync(path.resolve(__dirname, '../../backend/tests/integration/test_pomodoro_postgres_concurrency.py'), 'utf8')
function method(name, source = src, declaration = false) {
  const startToken = declaration ? `function ${name}(` : `  ${name}(`
  const asyncToken = `  async ${name}(`
  let start = source.indexOf(startToken)
  if (start < 0) start = source.indexOf(asyncToken)
  assert.ok(start >= 0, 'missing method ' + name)
  let brace = source.indexOf('{', start)
  let depth = 0, quote = '', escaped = false, line = false, block = false
  for (let i = brace; i < source.length; i++) {
    const ch = source[i], nx = source[i + 1]
    if (line) { if (ch === '\n') line = false; continue }
    if (block) { if (ch === '*' && nx === '/') { block = false; i++ } continue }
    if (quote) {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === quote) quote = ''
      continue
    }
    if (ch === '/' && nx === '/') { line = true; i++; continue }
    if (ch === '/' && nx === '*') { block = true; i++; continue }
    if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue }
    if (ch === '{') depth++
    if (ch === '}' && --depth === 0) return source.slice(start, i + 1)
  }
  return ''
}

console.log('\n--- Lifecycle race guards ---')
const onShow = method('onShow')
const onHide = method('onHide')
const onLoad = method('onLoad')
const onUnload = method('onUnload')
t('onShow versions active reconciliation', () => assert.ok(onShow.includes('activeSyncSeq')))
t('onShow ignores a response after the page is hidden', () => assert.ok(onShow.includes('!this._pageVisible || activeSyncSeq !== this._activeSyncSeq')))
t('onHide invalidates in-flight reconciliation', () => assert.ok(onHide.includes('this._activeSyncSeq = (this._activeSyncSeq || 0) + 1')))

console.log('\n--- Pause/resume tap stability ---')
const togglePause = method('togglePause')
const acquirePauseToggleLock = method('_acquirePauseToggleLock')
const releasePauseToggleLock = method('_releasePauseToggleLock')
t('pause/resume has a short independent tap cooldown', () => {
  assert.ok(src.includes('POMODORO_PAUSE_TOGGLE_COOLDOWN_MS = 500'))
  assert.ok(togglePause.includes('!this._acquirePauseToggleLock()'))
  assert.ok(acquirePauseToggleLock.includes('if (this._pauseToggleLocked) return false'))
  assert.ok(acquirePauseToggleLock.includes('setTimeout'))
  assert.ok(acquirePauseToggleLock.includes('POMODORO_PAUSE_TOGGLE_COOLDOWN_MS'))
})
t('tap cooldown does not reuse network actionLoading as its lock', () => {
  assert.ok(togglePause.includes('this.data.actionLoading'))
  assert.ok(acquirePauseToggleLock.includes('_pauseToggleLocked'))
  assert.ok(!acquirePauseToggleLock.includes('actionLoading'))
})
t('invalid/overlay pause taps are rejected before changing timer state', () => {
  assert.ok(togglePause.includes('this.data.phase !== PHASE.RUNNING'))
  assert.ok(togglePause.includes('!this._timerState.sessionId'))
  assert.ok(togglePause.includes('this.data.showEndConfirm'))
})
t('unload releases the pause toggle timer', () => {
  assert.ok(onUnload.includes('this._releasePauseToggleLock()'))
  assert.ok(releasePauseToggleLock.includes('clearTimeout(this._pauseToggleUnlockTimer)'))
})

console.log('\n--- Network reconnect drain ---')
const registerNetworkStatusListener = method('_registerNetworkStatusListener')
const unregisterNetworkStatusListener = method('_unregisterNetworkStatusListener')
t('network listener is registered once with a removable callback', () => {
  assert.ok(onLoad.includes('this._registerNetworkStatusListener()'))
  assert.ok(registerNetworkStatusListener.includes('this._getSyncRetryController().register()'))
})
t('network controller receives live page visibility and pending work', () => {
  const factory = method('_getSyncRetryController')
  assert.ok(factory.includes('isVisible: () => this._pageVisible'))
  assert.ok(factory.includes('hasPending: () => !!this._getPendingPomodoroSync()'))
  assert.ok(factory.includes('retry: () => this._retryPendingPomodoroSync()'))
})
t('network reconnect reuses existing terminal-conflict reconciliation', () => {
  const factory = method('_getSyncRetryController')
  assert.ok(factory.includes('_consumeAnyPomodoroTerminalConflict'))
  assert.ok(factory.includes('_handlePomodoroTerminalConflict'))
})
t('unload removes network callback to avoid page-instance leaks', () => {
  assert.ok(onUnload.includes('this._unregisterNetworkStatusListener()'))
  assert.ok(unregisterNetworkStatusListener.includes('this._syncRetryController.unregister()'))
})

console.log('\n--- Free cold restore / canonical clock ---')
const restoreFree = method('_restoreFreeSession')
t('free restore uses server start_time as the single clock origin', () => {
  assert.ok(restoreFree.includes('api.now() - startTime - totalPausedMs'))
  assert.ok(restoreFree.includes('this._timerState.freeDisplayOffsetMs = 0'))
  assert.ok(!restoreFree.includes('_localFreeDisplayOffsetMs'))
})
t('free restore caps display at five hours', () => assert.ok(restoreFree.includes('FREE_TIMER_MAX_MS')))
t('free elapsed helpers do not subtract a client-only startup offset', () => {
  assert.ok(!method('_getFreeElapsedMs').includes('displayOffsetMs'))
  assert.ok(!method('_getEffectiveFreeElapsedMs').includes('displayOffsetMs'))
})

console.log('\n--- Optimistic pause/resume ---')
for (const name of ['_pauseSession', '_pauseFreeTimer']) {
  const m = method(name)
  t(name + ' updates paused UI before network drain', () => {
    assert.ok(m.indexOf('isPaused: true') >= 0)
    assert.ok(m.indexOf('isPaused: true') < m.indexOf('_retryPendingPomodoroSync'))
  })
  t(name + ' persists a pending pause sync before changing local pause state', () => {
    assert.ok(m.includes("_setPendingPomodoroSync('pause'"))
    assert.ok(m.indexOf("_setPendingPomodoroSync('pause'") < m.indexOf('isPaused: true'))
    assert.ok(m.includes('_showPomodoroPersistenceError'))
  })
  t(name + ' releases actionLoading before network completes', () => {
    assert.ok(m.indexOf('actionLoading: false') < m.indexOf('_retryPendingPomodoroSync'))
  })
}
for (const name of ['_resumeSession', '_resumeFreeTimer']) {
  const m = method(name)
  t(name + ' updates running UI before network drain', () => {
    assert.ok(m.indexOf('isPaused: false') >= 0)
    assert.ok(m.indexOf('isPaused: false') < m.indexOf('_retryPendingPomodoroSync'))
  })
  t(name + ' persists a pending resume sync before changing local running state', () => {
    assert.ok(m.includes("_setPendingPomodoroSync('resume'"))
    assert.ok(m.indexOf("_setPendingPomodoroSync('resume'") < m.indexOf('isPaused: false'))
    assert.ok(m.includes('_showPomodoroPersistenceError'))
  })
  t(name + ' releases actionLoading before network completes', () => {
    assert.ok(m.indexOf('actionLoading: false') < m.indexOf('_retryPendingPomodoroSync'))
  })
}

console.log('\n--- Pending completion reliability ---')
const retry = method('_retryPendingPomodoroSync')
const complete = method('_completePomodoroWithRetry')
const queueReader = method('readQueue', queueSrc, true)
const queueMigration = method('migrateLegacyEntry', queueSrc, true)
t('all pending session mutations persist until server reconciliation', () => {
  assert.ok(!src.includes('POMODORO_PENDING_SYNC_TTL_MS'))
  assert.ok(!queueReader.includes('now - savedAt'))
  assert.ok(!queueReader.includes('savedAt <= now +'))
})
t('active local state has no fixed wall-clock expiry', () => {
  assert.ok(!src.includes('POMODORO_LOCAL_STATE_TTL_MS'))
  assert.ok(!method('_buildCachedActiveSession').includes('savedAt'))
})
t('pomodoro wall-clock calculations use server-adjusted api.now()', () => {
  assert.ok(src.includes('api.now()'))
  assert.ok(!src.includes('Date.now()'))
})
t('terminal response conflicts are reconciled by returned server status', () => {
  assert.ok(retry.includes("response.status !== expectedStatus"))
  assert.ok(retry.includes('_recordPomodoroTerminalConflict'))
})
t('pending sync storage is an ordered queue and migrates legacy single-slot data', () => {
  assert.ok(queueReader.includes('Array.isArray(raw)'))
  assert.ok(queueMigration.includes('list = [raw]'))
  assert.ok(queueSrc.includes('queue.push(pending)'))
})
t('legacy completeAfter is migrated into a terminal queue item', () => {
  assert.ok(queueMigration.includes('raw.completeAfter'))
  assert.ok(queueMigration.includes("action: 'complete'"))
})
t('queued mutations preserve client event timestamps for offline replay', () => {
  assert.ok(queueSrc.includes('clientActionAt'))
  assert.ok(retry.includes('client_action_at'))
})
t('pending queue drains strictly from the head', () => {
  assert.ok(retry.includes('const pending = queue[0]'))
  assert.ok(retry.includes('this._clearPendingPomodoroSync(pending)'))
})
t('permanent 404/409 queue failures reconcile against server active state', () => {
  assert.ok(retry.includes('_reconcilePendingPomodoroSyncFailure'))
  const reconcile = method('_reconcilePendingPomodoroSyncFailure')
  assert.ok(reconcile.includes('statusCode !== 404 && statusCode !== 409'))
  assert.ok(reconcile.includes("api.get('/pomodoro/active')"))
})
t('stale/too-early terminal actions restore the still-active server session', () => {
  const reconcile = method('_reconcilePendingPomodoroSyncFailure')
  assert.ok(reconcile.includes("error.code === 'POMODORO_STALE_ACTION'"))
  assert.ok(reconcile.includes("error.code === 'POMODORO_NOT_READY'"))
  assert.ok(reconcile.includes('this._restoreSession(active)'))
  assert.ok(reconcile.includes('this._clearPendingPomodoroSync(pending)'))
  assert.ok(reconcile.includes('showCelebration: false'))
})
t('clock-skew actions are recalibrated and replayed instead of silently deleted', () => {
  const reconcile = method('_reconcilePendingPomodoroSyncFailure')
  assert.ok(reconcile.includes("error.code === 'POMODORO_CLOCK_SKEW'"))
  assert.ok(reconcile.includes('_updatePendingPomodoroSync'))
  assert.ok(reconcile.includes('clientActionAt: api.now()'))
  assert.ok(reconcile.includes('clockSkewRetries'))
  assert.ok(reconcile.includes('return false'))
})
t('logout clears pending, unknown-start and terminal-conflict pomodoro mutations', () => {
  assert.ok(storageSrc.includes("'pomodoro_pending_sync'"))
  assert.ok(storageSrc.includes("'pomodoro_unknown_start'"))
  assert.ok(storageSrc.includes("'pomodoro_terminal_conflict'"))
})
t('terminal conflicts persist across process death before pending cleanup', () => {
  const record = method('_recordPomodoroTerminalConflict')
  const ack = method('_ackPomodoroTerminalConflict')
  const handle = method('_handlePomodoroTerminalConflict')
  assert.ok(record.includes('_safeSetPomodoroStorage(POMODORO_TERMINAL_CONFLICT_KEY'))
  assert.ok(record.includes('return false'))
  assert.ok(retry.includes('if (!this._recordPomodoroTerminalConflict'))
  assert.ok(retry.indexOf('if (!this._recordPomodoroTerminalConflict') < retry.indexOf('_dropPendingPomodoroSessionActions'))
  assert.ok(ack.includes('_safeRemovePomodoroStorage(POMODORO_TERMINAL_CONFLICT_KEY'))
  assert.ok(handle.indexOf('_dropPendingPomodoroSessionActions') < handle.indexOf('_ackPomodoroTerminalConflict'))
  assert.ok(onShow.includes('startupTerminalConflict'))
})
t('canonical pause/resume sync clears local adjustment only after the session queue is drained', () => {
  const retry = method('_retryPendingPomodoroSync')
  const maybeClear = method('_maybeClearLocalPauseAdjustment')
  assert.ok(retry.includes("pending.action === 'pause' || pending.action === 'resume'"))
  assert.ok(retry.includes('_maybeClearLocalPauseAdjustment(pending.sessionId)'))
  assert.ok(maybeClear.includes("_hasPendingPomodoroAction(sessionId, ['pause', 'resume'])"))
  assert.ok(method('_fetchActiveSession').includes("!this._hasPendingPomodoroAction(server.id, ['pause', 'resume'])"))
})
t('stale cross-device session actions are dropped after reconciliation', () => {
  const reconcile = method('_reconcilePendingPomodoroSyncFailure')
  assert.ok(reconcile.includes('_dropPendingPomodoroSessionActions(pending.sessionId)'))
})
t('completion is queued after earlier pause/resume actions', () => {
  assert.ok(complete.includes("_setPendingPomodoroSync('complete', sessionId, clientActionAt)"))
  assert.ok(complete.includes('_retryPendingPomodoroSync'))
})
t('automatic countdown completion uses retryable completion', () => assert.ok(method('_onWorkComplete').includes('_completePomodoroWithRetry')))
t('free completion uses retryable completion', () => assert.ok(method('_completeFreeTimerSession').includes('_completePomodoroWithRetry')))
t('cold-start pending terminal conflicts are consumed before keeping celebration state', () => {
  assert.ok(onShow.includes('_consumeAnyPomodoroTerminalConflict'))
})
t('expired countdown restore consumes terminal conflict from retry result', () => {
  const restore = method('_restoreSession')
  assert.ok(restore.includes("_consumePomodoroTerminalConflict(session.id, 'complete')"))
})

console.log('\n--- Long-term stability hardening ---')
const queueWriter = method('writeQueue', queueSrc, true)
const queueSetter = method('enqueueAction', queueSrc, true)
const retryScheduler = method('_schedulePendingPomodoroSyncRetry')
const retryClassifier = method('_isRetryablePomodoroSyncError')
const restoreCountdown = method('_restoreSession')
const statsLoader = method('loadTodayStats')
t('pending queue has a non-destructive safety valve and reserves terminal capacity', () => {
  assert.ok(queueSrc.includes('POMODORO_PENDING_SYNC_MAX_ACTIONS = 200'))
  assert.ok(queueSrc.includes('POMODORO_PENDING_SYNC_NON_TERMINAL_LIMIT = 196'))
  assert.ok(queueSetter.includes('const terminal ='))
  assert.ok(queueSetter.includes('queue.length >= limit'))
  assert.ok(queueSetter.includes('return null'))
  assert.ok(!queueSetter.includes('shift('))
  assert.ok(!queueSetter.includes('splice('))
})
t('pending queue persistence failures are surfaced instead of silently accepted', () => {
  assert.ok(queueWriter.includes('ctx.storage.write('))
  assert.ok(queueSetter.includes('return writeQueue(ctx, queue) ? pending : null'))
  assert.ok(queueSrc.includes('if (queue === null) return false'))
  assert.ok(retry.includes('local acknowledgement could not be persisted'))
})
t('online transient failures delegate to the tested retry controller', () => {
  assert.ok(retryClassifier.includes('return isRetryableSyncError(error)'))
  assert.ok(retryScheduler.includes('this._getSyncRetryController().schedule(error)'))
  assert.ok(retry.includes('_schedulePendingPomodoroSyncRetry(error)'))
})
t('retry timers stop while hidden/unloaded and reconnect retries immediately', () => {
  assert.ok(onHide.includes('_clearPendingPomodoroSyncRetryTimer()'))
  assert.ok(onUnload.includes('_clearPendingPomodoroSyncRetryTimer(true)'))
  assert.ok(registerNetworkStatusListener.includes('this._getSyncRetryController().register()'))
})
t('countdown cold restore treats a valid pause snapshot as authoritative even at 0ms', () => {
  assert.ok(restoreCountdown.includes('savedTotal + Math.max(0, api.now() - pauseStart)'))
  assert.ok(restoreCountdown.includes('isPaused = true'))
  assert.ok(!restoreCountdown.includes('isPaused = totalPausedMs > 0'))
})
t('today stats ignores slower stale responses', () => {
  assert.ok(statsLoader.includes('_statsRequestSeq'))
  assert.ok(statsLoader.includes('requestSeq !== this._statsRequestSeq'))
  assert.ok(onUnload.includes('_statsRequestSeq = (this._statsRequestSeq || 0) + 1'))
})
t('corrective database migration is fail-loud and verifies all canonical invariants', () => {
  assert.ok(backendCorrectiveMigrationSrc.includes('down_revision: str | None = "x8y9z0a1b2c3"'))
  assert.ok(backendCorrectiveMigrationSrc.includes('_validate_legacy_data'))
  assert.ok(backendCorrectiveMigrationSrc.includes('raise RuntimeError'))
  assert.ok(backendCorrectiveMigrationSrc.includes('_verify_postconditions'))
  assert.ok(backendCorrectiveMigrationSrc.includes('ux_pomodoro_sessions_one_active_per_user'))
  assert.ok(backendCorrectiveMigrationSrc.includes('ux_pomodoro_sessions_user_client_start_id'))
})
t('definition migration validates columns, uniqueness and partial predicates', () => {
  assert.ok(backendDefinitionMigrationSrc.includes('down_revision: str | None = "y9z0a1b2c3d4"'))
  assert.ok(backendDefinitionMigrationSrc.includes('_index_matches'))
  assert.ok(backendDefinitionMigrationSrc.includes('column_names'))
  assert.ok(backendDefinitionMigrationSrc.includes('predicate_tokens'))
  assert.ok(backendDefinitionMigrationSrc.includes('duplicate_active'))
  assert.ok(backendDefinitionMigrationSrc.includes('duplicate_client_start'))
  assert.ok(backendDefinitionMigrationSrc.includes('_verify_postconditions'))
})
t('real PostgreSQL concurrency regression is available for CI', () => {
  assert.ok(backendPostgresConcurrencyTestSrc.includes('POMODORO_TEST_POSTGRES_URL'))
  assert.ok(backendPostgresConcurrencyTestSrc.includes('FOR UPDATE'))
  assert.ok(backendPostgresConcurrencyTestSrc.includes('UniqueViolationError'))
  assert.ok(backendPostgresConcurrencyTestSrc.includes('resume unexpectedly bypassed the row lock'))
  assert.ok(backendPostgresConcurrencyTestSrc.includes('pomodoro_service.start_session'))
  assert.ok(backendPostgresConcurrencyTestSrc.includes('pomodoro_service.pause_session'))
  assert.ok(backendPostgresConcurrencyTestSrc.includes('pomodoro_service.resume_session'))
  assert.ok(backendPostgresConcurrencyTestSrc.includes('pomodoro_service.interrupt_session'))
})


t('critical active-session restore reads fail closed', () => {
  const cached = method('_getCachedActiveSession')
  const fetchActive = method('_fetchActiveSession')
  assert.ok(cached.includes("_safeGetPomodoroStorage('pomodoro_running_state'"))
  assert.ok(cached.includes('storageUnreadable: true'))
  assert.ok(fetchActive.includes("_safeGetPomodoroStorage('pomodoro_running_state'"))
  assert.ok(fetchActive.includes('storageUnreadable: true'))
  assert.ok(restoreCountdown.includes("_safeGetPomodoroStorage('pomodoro_confirm_pause'"))
  assert.ok(restoreCountdown.includes("_safeGetPomodoroStorage('pomodoro_pause'"))
  assert.ok(restoreFree.includes("_safeGetPomodoroStorage('pomodoro_free_pause'"))
})
t('pause adjustment read failures are distinguishable during cold restore', () => {
  const adjustment = method('_getLocalPauseAdjustment')
  const merge = method('_mergeLocalPauseAdjustment')
  assert.ok(adjustment.includes('failClosed ? null : 0'))
  assert.ok(merge.includes('if (localPausedMs === null) return null'))
  assert.ok(restoreCountdown.includes('_mergeLocalPauseAdjustment(session.id, totalPausedMs, true)'))
  assert.ok(restoreFree.includes('_mergeLocalPauseAdjustment(session.id, totalPausedMs, true)'))
})
t('terminal conflict acknowledgement is durable and happens after cleanup', () => {
  const consume = method('_consumePomodoroTerminalConflict')
  const ack = method('_ackPomodoroTerminalConflict')
  const handle = method('_handlePomodoroTerminalConflict')
  assert.ok(!consume.includes('_safeRemovePomodoroStorage(POMODORO_TERMINAL_CONFLICT_KEY'))
  assert.ok(ack.includes('_safeRemovePomodoroStorage(POMODORO_TERMINAL_CONFLICT_KEY'))
  assert.ok(handle.indexOf("_safeGetPomodoroStorage('pomodoro_completion'") < handle.indexOf('_ackPomodoroTerminalConflict'))
  assert.ok(handle.indexOf('_dropPendingPomodoroSessionActions') < handle.indexOf('_ackPomodoroTerminalConflict'))
})

t('pending queue read failures fail closed instead of masquerading as empty', () => {
  assert.ok(queueReader.includes("if (!stored.ok) return null"))
  assert.ok(queueSrc.includes('if (queue === null) return null'))
  assert.ok(retry.includes('if (queue === null)'))
  assert.ok(onShow.includes('pendingSync.storageUnreadable'))
  assert.ok(onShow.indexOf('pendingSync.storageUnreadable') < onShow.indexOf('_reconcileUnknownStartAttempt()'))
})
t('start request is gated on durable unknown-start recovery state', () => {
  const startPost = method('_postPomodoroStartWithReconciliation')
  assert.ok(startPost.includes("_safeSetPomodoroStorage(POMODORO_UNKNOWN_START_KEY"))
  assert.ok(startPost.indexOf("_safeSetPomodoroStorage(POMODORO_UNKNOWN_START_KEY") < startPost.indexOf("api.post('/pomodoro/start'"))
  assert.ok(startPost.includes("_safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'accepted pomodoro start')"))
})
t('late start response retains exact cancel credential when pending persistence fails', () => {
  const startPost = method('_postPomodoroStartWithReconciliation')
  assert.ok(startPost.includes("const pending = this._setPendingPomodoroSync('interrupt'"))
  assert.ok(startPost.includes('cancelIfFound: true'))
  assert.ok(startPost.includes("'retain cancelled start after response'"))
})
t('critical pomodoro lifecycle storage mutations use guarded helpers', () => {
  const unsafe = /wx\.(?:setStorageSync|removeStorageSync)\('pomodoro_(?:completion|confirm_pause|running_state|pause|free_pause|pause_adjustment|break)'/g
  assert.deepStrictEqual(src.match(unsafe) || [], [])
})

console.log('\n--- Server-authoritative countdown completion ---')
t('backend rejects early non-debug countdown completion', () => {
  assert.ok(backendServiceSrc.includes('class PomodoroNotReadyError'))
  assert.ok(backendServiceSrc.includes('COUNTDOWN_COMPLETE_EARLY_TOLERANCE_SEC = 2'))
  assert.ok(backendServiceSrc.includes('session.preset in ("free", "debug")'))
  assert.ok(backendServiceSrc.includes('_countdown_completion_ready'))
  assert.ok(backendServiceSrc.includes('raise PomodoroNotReadyError("POMODORO_NOT_READY")'))
})
t('earliest valid terminal action wins and truncates later pause events', () => {
  assert.ok(backendServiceSrc.includes('def _truncate_pause_timeline_at'))
  assert.ok(backendServiceSrc.includes('reject_stale_before=None'))
  assert.ok(backendServiceSrc.includes('if action_time >= session.end_time'))
  assert.ok(backendServiceSrc.includes('requested_status="interrupted"'))
  assert.ok(backendServiceSrc.includes('requested_status="completed"'))
})
t('same-state delayed pause/resume can repair canonical interval timing', () => {
  assert.ok(backendServiceSrc.includes('if session.status == "paused":'))
  assert.ok(backendServiceSrc.includes('if action_time < open_interval.started_at'))
  assert.ok(backendServiceSrc.includes('latest_closed.ended_at == latest_event'))
  assert.ok(backendServiceSrc.includes('if action_time < latest_closed.ended_at'))
})
t('backend rejects client actions implausibly ahead of or before the session clock', () => {
  assert.ok(backendServiceSrc.includes('CLIENT_ACTION_FUTURE_TOLERANCE_SEC = 5'))
  assert.ok(backendServiceSrc.includes('CLIENT_ACTION_PAST_TOLERANCE_SEC = 5'))
  assert.ok(backendServiceSrc.includes('candidate < session.start_time - timedelta'))
  assert.ok(backendServiceSrc.includes('class PomodoroClockSkewError'))
  assert.ok(backendServiceSrc.includes('raise PomodoroClockSkewError("POMODORO_CLOCK_SKEW")'))
  assert.ok(backendApiSrc.includes('"POMODORO_CLOCK_SKEW"'))
})
t('complete endpoint exposes early completion as a 409 machine-readable conflict', () => {
  assert.ok(backendApiSrc.includes('except svc.PomodoroNotReadyError'))
  assert.ok(backendApiSrc.includes('"POMODORO_NOT_READY"'))
})

console.log('\n--- Start lifecycle guards ---')
const startSession = method('startSession')
const startFree = method('_startFreeSession')
const postStart = method('_postPomodoroStartWithReconciliation')
const reconcileStart = method('_reconcileUnknownStartAttempt')
t('start ceremony uses a lifecycle generation', () => assert.ok(startSession.includes('_startRequestSeq')))
t('start has a dedicated in-flight lock against rapid double taps', () => {
  assert.ok(startSession.includes('this._startInFlight'))
  assert.ok(startSession.includes('finally'))
  assert.ok(startSession.includes('this._startInFlight = false'))
})
t('start ceremony aborts before POST after page hide', () => {
  assert.ok(startSession.includes('!this._pageVisible || startSeq !== this._startRequestSeq'))
  assert.ok(startSession.indexOf('!this._pageVisible || startSeq !== this._startRequestSeq') < startSession.indexOf('_postPomodoroStartWithReconciliation'))
})
t('late start response is queued for interrupt instead of becoming a ghost session', () => {
  assert.ok(postStart.includes("'interrupt'"))
  assert.ok(postStart.includes('session.id'))
  assert.ok(postStart.includes('_startCancellationAt(session, latestAttempt.cancelAt)'))
  assert.ok(method('_startCancellationAt').includes('Math.max(serverStartAt, fallback)'))
  assert.ok(startSession.includes('_postPomodoroStartWithReconciliation'))
  assert.ok(startFree.includes('_postPomodoroStartWithReconciliation'))
})
t('start uncertainty is persisted before POST and retried with the same idempotency key', () => {
  assert.ok(postStart.indexOf('wx.setStorageSync(POMODORO_UNKNOWN_START_KEY') < postStart.indexOf("api.post('/pomodoro/start'"))
  assert.ok(postStart.includes('api.createClientStartId()'))
  assert.ok(reconcileStart.includes("api.post('/pomodoro/start', payload)"))
  assert.ok(reconcileStart.includes('_matchesUnknownStartAttempt'))
  assert.ok(!reconcileStart.includes("api.get('/pomodoro/active')"))
})
t('unknown-start matching uses exact client_start_id, not preset/time-window guessing', () => {
  const match = method('_matchesUnknownStartAttempt')
  assert.ok(match.includes('session.client_start_id === attempt.clientStartId'))
  assert.ok(!match.includes('work_duration'))
  assert.ok(!match.includes('start_time'))
})
t('backend persists a per-user client_start_id unique key and checks it before active guard', () => {
  assert.ok(backendSchemaSrc.includes('client_start_id'))
  assert.ok(backendModelSrc.includes('ux_pomodoro_sessions_user_client_start_id'))
  assert.ok(backendMigrationSrc.includes('down_revision: str | None = "w7x8y9z0a1b2"'))
  const startIdx = backendServiceSrc.indexOf('async def start_session(')
  const keyIdx = backendServiceSrc.indexOf('_get_session_by_client_start_id', startIdx)
  const activeIdx = backendServiceSrc.indexOf('active = await get_active_session', startIdx)
  assert.ok(keyIdx > startIdx && keyIdx < activeIdx)
  assert.ok(backendApiSrc.includes('client_start_id=req.client_start_id'))
})
t('leaving during an uncertain start only cancels the exact idempotent session', () => {
  assert.ok(onHide.includes('cancelIfFound: true'))
  assert.ok(onHide.includes('cancelAt: api.now()'))
  assert.ok(reconcileStart.includes('storedAttempt.clientStartId === attempt.clientStartId'))
  assert.ok(reconcileStart.includes('attempt.cancelIfFound &&'))
  assert.ok(reconcileStart.includes('_matchesUnknownStartAttempt(session, attempt)'))
})
t('new starts reconcile any unresolved prior idempotency key before creating another', () => {
  assert.ok(startSession.includes('const unresolvedStart = await this._reconcileUnknownStartAttempt()'))
  assert.ok(startSession.includes("unresolvedStart === 'offline'"))
  assert.ok(startSession.indexOf('_reconcileUnknownStartAttempt()') < startSession.indexOf('_postPomodoroStartWithReconciliation'))
})
t('onHide invalidates in-flight start requests', () => assert.ok(onHide.includes('_startRequestSeq = (this._startRequestSeq || 0) + 1')))

console.log('\n--- Server clock calibration ---')
t('API clock offset uses request/response RTT midpoint', () => {
  assert.ok(apiSrc.includes('const clientMidpointMs = startedAt + rttMs / 2'))
  assert.ok(apiSrc.includes('const candidateOffsetMs = serverMs - clientMidpointMs'))
})
t('clock calibration prefers explicit server_now and better RTT samples', () => {
  assert.ok(apiSrc.includes('sourceRank = 2'))
  assert.ok(apiSrc.includes('_serverClockBestRttMs'))
  assert.ok(apiSrc.includes('rttImproved'))
})

console.log('\n--- Canonical start-time display ---')
t('new countdown derives remaining time from server start_time', () => {
  const m = method('_beginCountdown')
  assert.ok(m.includes('api.now() - startTime - totalPausedMs'))
  assert.ok(m.includes('remainingMs'))
  assert.ok(!m.includes('Date.now() + totalSec * 1000'))
})
t('new free timer immediately displays server elapsed time', () => {
  const m = method('_beginFreeTimer')
  assert.ok(m.includes('now - startTime - totalPausedMs'))
  assert.ok(m.includes('freeDisplayTime: fmt.display'))
  assert.ok(m.includes('freeDisplayOffsetMs = 0'))
})

console.log('\n--- Completion lifecycle ---')
const showCompletion = method('_showCompletionCelebration')
const dismissCompletion = method('dismissCelebration')
t('natural completion clears running snapshots before showing celebration', () => {
  assert.ok(showCompletion.includes("_safeRemovePomodoroStorage('pomodoro_running_state'"))
  assert.ok(showCompletion.indexOf("_safeRemovePomodoroStorage('pomodoro_running_state'") < showCompletion.indexOf('showCelebration: true'))
})
t('completion marker persists break metadata across app restart', () => {
  assert.ok(showCompletion.includes('breakSec'))
  assert.ok(showCompletion.includes('breakDuration'))
  assert.ok(dismissCompletion.includes('completionFlag.breakSec'))
})
t('onShow keeps a valid completion marker authoritative until dismissal', () => {
  assert.ok(onShow.includes('phase: PHASE.IDLE'))
  assert.ok(onShow.includes('showCelebration: true'))
  const completionSection = onShow.slice(onShow.indexOf("const completionFlag = wx.getStorageSync('pomodoro_completion')"), onShow.indexOf('// Navigation guard'))
  assert.ok(!completionSection.includes("else {\n        wx.removeStorageSync('pomodoro_completion')"))
})

console.log('\n--- Break restore ---')
const startBreak = method('_startBreak')
const restoreBreak = method('_restoreBreak')
t('break restore preserves original start time and total duration', () => {
  assert.ok(src.includes('breakStartTime + totalMs - api.now()'))
  assert.ok(restoreBreak.includes('startTime: Number(saved.startTime)'))
  assert.ok(restoreBreak.includes('Number(saved.totalSec)'))
})
t('break progress is based on original total instead of rebasing to remaining', () => {
  assert.ok(src.includes('this._timerState.progress = remainingMs / totalMs'))
  assert.ok(!restoreBreak.includes('_startBreak(remaining'))
})
t('onShow restores break before pending network synchronization', () => {
  assert.ok(onShow.indexOf('restoredBreak = this._restoreBreak()') < onShow.indexOf('await this._retryPendingPomodoroSync()'))
})

console.log('\n--- Canvas reuse ---')
const startTimer = method('_startTimer')
const initCanvas = method('_initCanvas')
t('timer restart can reuse an existing/in-flight canvas', () => assert.ok(src.includes('this._initCanvas(!options.reuseCanvas)')))
t('canvas init suppresses duplicate in-flight initialization', () => assert.ok(initCanvas.includes('this._canvasInitPending')))
t('canvas initialization waits substantially longer on slow devices', () => {
  assert.ok(src.includes('CANVAS_INIT_MAX_RETRIES = 16'))
  assert.ok(method('_scheduleCanvasInit').includes('retryCount * 8'))
})
t('drawRing self-heals a failed canvas initialization on a later tick', () => {
  const draw = method('drawRing')
  assert.ok(draw.includes('!this._canvasInitPending'))
  assert.ok(draw.includes('this._initCanvas(false)'))
})

console.log('\n--- Free end-confirm ring recovery ---')
const cancelEndConfirm = method('cancelEndConfirm')
const redrawFreeRing = method('_redrawFreeRingAfterOverlay')
t('free ring recovery forces a fresh canvas after overlay dismissal', () => {
  assert.ok(redrawFreeRing.includes('this._timerState.progress = 1'))
  assert.ok(redrawFreeRing.includes('this._initCanvas(true)'))
  assert.ok(redrawFreeRing.includes('this.drawRing(0, false)'))
})
t('free end-confirm cancel redraws the ring in all recovery branches', () => {
  const hits = cancelEndConfirm.match(/this\._redrawFreeRingAfterOverlay\(\)/g) || []
  assert.ok(hits.length >= 3, 'expected redraw in fallback, paused and running branches')
})
t('free ring redraw waits until the confirm overlay is gone', () => {
  assert.ok(redrawFreeRing.includes('wx.nextTick'))
  assert.ok(redrawFreeRing.includes('this.data.showEndConfirm'))
})

console.log('\n--- Canvas re-entry positioning ---')
const wxml = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.wxml'), 'utf8')
const wxss = fs.readFileSync(path.resolve(__dirname, '../pages/pomodoro/pomodoro.wxss'), 'utf8')
t('long confirm copy has an explicit third line for large-font safety', () => {
  assert.ok(wxml.includes('endConfirmLine3'))
  assert.ok(src.includes("endConfirmLine3: hasElapsed ? '确认后将计入学习统计。' : ''"))
})
t('native canvas is truly hidden while end-confirm overlay is visible', () => {
  // Native Canvas can sit above cover-view on real devices even when CSS opacity is 0.
  // The confirm overlay must therefore use the native `hidden` switch; cancel paths
  // already force a stable-layout canvas rebuild before revealing it again.
  assert.ok(wxml.includes('hidden="{{showEndConfirm || !ringCanvasVisible}}"'))
})

t('countdown cancel rebuilds canvas after native hidden is removed', () => {
  const countdown = cancelEndConfirm.slice(cancelEndConfirm.indexOf("if (mode === 'countdown-interrupt'"), cancelEndConfirm.indexOf("if (mode === 'free-complete')"))
  const initHits = countdown.match(/this\._initCanvas\(true\)/g) || []
  const drawHits = countdown.match(/this\.drawRing\(/g) || []
  assert.ok(initHits.length >= 2, 'expected paused and running countdown cancel branches to rebuild canvas')
  assert.ok(drawHits.length >= 2, 'expected paused and running countdown cancel branches to redraw ring')
})
t('native canvas uses normal flow instead of absolute positioning', () => {
  const block = wxss.slice(wxss.indexOf('.ring-canvas {'), wxss.indexOf('.ring-canvas-ready'))
  assert.ok(block.includes('position: relative'))
  assert.ok(!block.includes('position: absolute'))
})
t('ring wrapper fills the stage without absolute positioning', () => {
  const start = wxss.indexOf('.ring-wrapper {')
  const end = wxss.indexOf('}', start)
  const block = wxss.slice(start, end + 1)
  assert.ok(block.includes('position: relative'))
  assert.ok(block.includes('width: 100%'))
  assert.ok(block.includes('height: 100%'))
})
t('canvas init ignores stale selector callbacks by generation', () => {
  assert.ok(initCanvas.includes('_canvasInitSeq'))
  assert.ok(method('_scheduleCanvasInit').includes('initSeq !== this._canvasInitSeq'))
})
t('canvas waits for a stable stage-aligned layout before binding context', () => {
  const m = method('_scheduleCanvasInit')
  assert.ok(m.includes("select('.ring-stage').boundingClientRect()"))
  assert.ok(m.includes('stageAligned'))
  assert.ok(m.includes('stable'))
})
t('canvas is revealed only after a successful draw', () => {
  assert.ok(src.includes('ringCanvasPaintReady: false'))
  assert.ok(method('drawRing').includes('this.setData({ ringCanvasPaintReady: true })'))
})
t('reset-to-idle invalidates stale canvas init callbacks', () => {
  assert.ok(method('_resetToIdle').includes('this._canvasInitSeq = (this._canvasInitSeq || 0) + 1'))
})
t('free light-sync rebuilds canvas if page-hide interrupted initialization', () => {
  const m = method('_syncActiveSessionLight')
  assert.ok(m.includes('if (!this._canvasReady || !this._ctx)'))
  assert.ok(m.includes('this.drawRing(0, false)'))
})
t('hide always discards native canvas context', () => {
  assert.ok(onHide.includes('this._canvasReady = false'))
  assert.ok(onHide.includes('this._ctx = null'))
  assert.ok(!onHide.includes('if (this._canvasInitPending)'))
})
t('unload invalidates in-flight canvas initialization', () => {
  assert.ok(onUnload.includes('this._canvasInitSeq = (this._canvasInitSeq || 0) + 1'))
})

console.log('\n==============================')
console.log('Passed:', passed, ' Failed:', failed)
console.log('==============================\n')
if (failed) process.exit(1)

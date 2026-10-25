const api = require('../../utils/api')
const { readStorage, writeStorage, removeStorage } = require('./utils/session-storage')
const { createPendingSyncQueue } = require('./utils/pending-sync-queue')
const { createSyncRetryController, isRetryableSyncError } = require('./utils/sync-retry-controller')
const { recoverActiveSession } = require('./utils/active-session-recovery')
const { buildCompletionRecovery } = require('./utils/completion-recovery')
const { restoreConfirmSnapshot } = require('./utils/confirm-recovery')
const { recoverOnShow } = require('./utils/show-recovery')
const { cancelUnknownStartOnHide, persistSessionOnHide } = require('./utils/hide-storage')
const { filter408SubjectTree } = require('./utils/subject-scope')
const {
  readSubjectCache,
  writeSubjectCache,
} = require('./utils/subject-cache')
const config = require('../../config')
const { safeDecodeURIComponent } = require('./utils/route-params')
const pomodoroTheme = require('./utils/pomodoro-theme')
const { buildSubjectChoices, subjectIconByCode } = require('./utils/subject-options')
const { buildApplySubjectsPlan } = require('./utils/apply-subjects-controller')
const { buildEffectivePausedMs } = require('./utils/effective-paused-ms')
const { createCountdownController } = require('./utils/countdown-controller')
const { createFreeTimerController } = require('./utils/free-timer-controller')
const { buildRingCache, shouldDrawRing } = require('./utils/ring-geometry')
const conflictState = require('./utils/terminal-conflict-state')
const { CANVAS_INIT_MAX_RETRIES } = require('./utils/canvas-layout')
const {
  canReconcilePendingSync,
  decidePendingSyncReconciliation,
} = require('./utils/sync-reconciliation')
const {
  resolvePausedMs,
  computeCountdownRestore,
  computeFreeRestore,
  resolveRestoredSubject,
} = require('./utils/session-restore')
const {
  createCountdownSessionRestoreController,
} = require('./utils/countdown-session-restore-controller')
const { createFreeSessionRestoreController } = require('./utils/free-session-restore-controller')
const { createStartSessionController } = require('./utils/start-session-controller')
const { createUnknownStartController } = require('./utils/unknown-start-controller')
const { createPendingSyncController } = require('./utils/pending-sync-controller')
const { createTerminalConflictController } = require('./utils/terminal-conflict-controller')
const { createStatsController } = require('./utils/stats-controller')
const { createThemeController } = require('./utils/theme-controller')
const {
  isValidConfirmSnapshot,
  buildFreeConfirmSnapshot,
  buildCountdownInterruptSnapshot,
} = require('./utils/end-confirm-snapshot')
const { createActiveSyncController } = require('./utils/active-sync-controller')
const { createPauseToggleController } = require('./utils/pause-toggle-controller')
const { createPomodoroPauseSyncController } = require('./utils/pause-sync-controller')
const { createResumeErrorController } = require('./utils/resume-error-controller')
const { createCelebrationDismissController } = require('./utils/celebration-dismiss-controller')
const { createBreakRestoreController } = require('./utils/break-restore-controller')
const { createCompletionCelebrationController } = require('./utils/completion-celebration-controller')
const { createWorkCompleteController } = require('./utils/work-complete-controller')
const { createFreeTimerBeginController } = require('./utils/free-timer-begin-controller')
const { createCancelEndConfirmController } = require('./utils/cancel-end-confirm-controller')
const { createShowEndFreeConfirmController } = require('./utils/show-end-free-confirm-controller')
const { createPauseCountdownEndConfirmController } = require('./utils/pause-countdown-end-confirm-controller')
const { createConfirmInterruptCountdownController } = require('./utils/confirm-interrupt-countdown-controller')
const { createResetToIdleController } = require('./utils/reset-to-idle-controller')
const { createUpdateFreeElapsedController } = require('./utils/update-free-elapsed-controller')
const { createBeginCountdownController } = require('./utils/begin-countdown-controller')
const { createPauseSessionController } = require('./utils/pause-session-controller')
const { createResumeSessionController } = require('./utils/resume-session-controller')
const { createShowCountdownInterruptConfirmController } = require('./utils/show-countdown-interrupt-confirm-controller')
const { createConfirmEndTimerController } = require('./utils/confirm-end-timer-controller')
const { createEndSessionController } = require('./utils/end-session-controller')
const { createPauseFreeTimerController } = require('./utils/pause-free-timer-controller')
const { createResumeFreeTimerController } = require('./utils/resume-free-timer-controller')
const { createInterruptSessionController } = require('./utils/interrupt-session-controller')
const { createConfirmEndFreeTimerController } = require('./utils/confirm-end-free-timer-controller')
const { createFreeTimerLimitController } = require('./utils/free-timer-limit-controller')
const { createFreeElapsedController } = require('./utils/free-elapsed-controller')
const { createStartBreakController } = require('./utils/start-break-controller')
const { createStartTimerController } = require('./utils/start-timer-controller')
const { createCanvasInitController } = require('./utils/canvas-init-controller')
const { createDrawRingController } = require('./utils/draw-ring-controller')
const { createSkipBreakController } = require('./utils/skip-break-controller')
const { createFontSizeController } = require('./utils/font-size-controller')
const { createSubjectViewController } = require('./utils/subject-view-controller')
const { createPresetViewController } = require('./utils/preset-view-controller')
const { createCelebrationTypeController } = require('./utils/celebration-type-controller')
const { createDateExamController } = require('./utils/date-exam-controller')
const { buildCancelEndConfirmPlan } = require('./utils/cancel-confirm-state')
const {
  findSubjectById,
} = require('./utils/subject-selection')
const { formatElapsedSec, formatCountdownDisplay } = require('./utils/timer-math')
const { buildCompletionCelebration } = require('./utils/completion-celebration')
const { handleTerminalConflict } = require('./utils/terminal-conflict-handler')
const {
  getLocalPauseAdjustment,
  mergeLocalPauseAdjustment,
  clearLocalPauseAdjustment,
} = require('./utils/pause-adjustment')
const { resolveBreakSec } = require('./utils/celebration-dismiss')
const { buildEndConfirmViewModel } = require('./utils/end-confirm-view-model')
const {
  buildUnknownStartPayload,
  matchesUnknownStartAttempt,
  buildUnknownStartAttempt,
  startCancellationAt,
} = require('./utils/unknown-start-helpers')
const { buildCachedActiveSession } = require('./utils/cached-session-builder')
const { parseServerUtc, getChinaWallParts, getChinaDayStartUtcMs } = require('../../utils/china-time')
const { pomodoroTaskTypes } = require('../../utils/storage')

const PHASE = { IDLE: 'idle', RUNNING: 'running', BREAK: 'break', CEREMONY: 'ceremony' }

const PRESETS = [
  { key: 'standard', label: '标准', work: 25, break: 5 },
  { key: 'long', label: '长时间', work: 50, break: 10 },
  { key: 'custom', label: '自定义', work: 25, break: 5 },
  { key: 'free', label: '自由计时', work: 0, break: 0 },
]

const FREE_TIMER_MAX_MS = 5 * 60 * 60 * 1000 // 5 hours max for free timer
const POMODORO_UNKNOWN_START_KEY = 'pomodoro_unknown_start'
const POMODORO_TERMINAL_CONFLICT_KEY = 'pomodoro_terminal_conflict'
const POMODORO_PAUSE_TOGGLE_COOLDOWN_MS = 500

function parseServerTime(value) {
  return parseServerUtc(value)
}

const MOTTOES = [
  '击败了昨天的自己',
  '每一步都算数',
  '坚持就是胜利',
  '离上岸又近一步',
  '今天的你比昨天更强',
  '积少成多，聚沙成塔',
  '专注是最好的努力',
  '为梦想全力以赴',
]

Page({
  data: {
    phase: PHASE.IDLE,
    subjects: [],
    subjectsLoading: true,
    subjectsError: '',
    selectedSubjectId: null,
    selectedSubject: null,
    allocationMode: 'single',
    aggregateAvailable: false,
    coreSubjects: [],
    taskTypes: pomodoroTaskTypes.TYPES,
    selectedTaskType: pomodoroTaskTypes.DEFAULT_TYPE,
    selectedTaskTypeLabel: pomodoroTaskTypes.label(pomodoroTaskTypes.DEFAULT_TYPE),
    presets: PRESETS,
    selectedPreset: 'standard',
    workDuration: 25,
    breakDuration: 5,
    showCustom: false,
    isPaused: false,

    // free timer fields
    isFreeTimer: false,
    freeDisplayTime: '00:00:00',
    showEndConfirm: false,
    endConfirmTheme: '',
    endConfirmTitle: '',
    endConfirmText: '',
    endConfirmLine1: '',
    endConfirmLine2: '',
    endConfirmLine3: '',
    endConfirmOkText: '确认结束',
    endConfirmCancelText: '继续计时',
    actionLoading: false,

    // timer display
    displayMin: '00',
    displaySec: '00',
    // today stats
    todaySessions: 0,
    todayDurationText: '0分钟',

    // practice page context
    fromSubjectId: null,
    fromSubjectCode: '',
    fromChapterId: '',
    fromChapterName: '',

    // font size accessibility
    fontSizeLevel: 'medium',

    // shared light/dark theme (default light, stored per local user)
    themeMode: 'light',
    themeSwitching: false,
    sliderBlockColor: '#153323',
    sliderTrackColor: 'rgba(21,51,35,0.12)',
    celebrationTheme: 'light',

    // new features
    examDays: 0,
    showCelebration: false,
    celebrationMotto: '',
    celebrationType: 'excellent',
    pageEntered: false,
    debugMode: false,
    ringCanvasVisible: true,
    ringCanvasPaintReady: false,
    selectedSubjectLabel: '',
    selectedPresetLabel: '',
  },

  _timerController: null,
  _freeTimerController: null,
  _freeTimerFinalizing: false,
  _touchStartX: 0,
  _pageVisible: false,
  _debugTapCount: 0,
  _debugTapTimer: null,
  _countdownEndAt: 0,
  _countdownTotalSec: 0,
  _countdownRemainingSnapshot: null,
  _confirmTimerSnapshot: null,
  _lastDrawnProgress: undefined,
  _lastDrawnIsBreak: undefined,
  _ringCache: null,
  _canvasInitSeq: 0,
  _startInFlight: false,
  _completionBreakSec: null,
  _syncRetryController: null,
  _statsController: null,
  _themeController: null,
  _activeSyncController: null,
  _pauseToggleController: null,
  _resumeErrorController: null,
  _celebrationDismissController: null,
  _breakRestoreController: null,
  _completionCelebrationController: null,
  _workCompleteController: null,
  _freeTimerBeginController: null,
  _cancelEndConfirmController: null,
  _showEndFreeConfirmController: null,
  _pauseCountdownEndConfirmController: null,
  _confirmInterruptCountdownController: null,
  _resetToIdleController: null,
  _updateFreeElapsedController: null,
  _beginCountdownController: null,
  _pauseSessionController: null,
  _resumeSessionController: null,
  _showCountdownInterruptConfirmController: null,
  _confirmEndTimerController: null,
  _endSessionController: null,
  _pauseFreeTimerController: null,
  _resumeFreeTimerController: null,
  _interruptSessionController: null,
  _confirmEndFreeTimerController: null,
  _freeTimerLimitController: null,
  _freeElapsedController: null,
  _startBreakController: null,
  _startTimerController: null,
  _canvasInitController: null,
  _drawRingController: null,
  _freeSessionRestoreController: null,
  _countdownSessionRestoreController: null,
  _startSessionController: null,
  _unknownStartController: null,
  _pendingSyncController: null,
  _terminalConflictController: null,

  /* ==================== Lifecycle ==================== */

  _createTimerState() {
    return {
      sessionId: null,
      sessionStartTime: null,
      breakStartTime: null,
      totalPausedMs: 0,
      pauseStartTime: null,
      elapsedSec: 0,
      remainingSec: 0,
      endConfirmMode: '',
      freeFriendlyText: '',
      freeDisplayOffsetMs: 0,
      progress: 1,
      todayDurationSec: 0,
    }
  },

  onLoad(opts) {
    this._timerState = this._createTimerState()
    this._registerNetworkStatusListener()
    const themeMode = pomodoroTheme.getTheme()
    pomodoroTheme.applyNativeTheme(themeMode)
    const routeTaskType = opts && opts.task_type ? pomodoroTaskTypes.normalize(String(opts.task_type)) : pomodoroTaskTypes.getSelected()
    this.setData({
      examDays: this._getExamDays(),
      fontSizeLevel: wx.getStorageSync('pomodoro_font_size') || 'medium',
      selectedTaskType: routeTaskType,
      selectedTaskTypeLabel: pomodoroTaskTypes.label(routeTaskType),
      fromSubjectId: opts && opts.subject_id ? Number(opts.subject_id) : null,
      fromSubjectCode: String((opts && opts.subject_code) || ''),
      ...this._getThemeViewModel(themeMode),
    })
    this._loadSubjects()

    if (opts.chapterId) this.setData({ fromChapterId: opts.chapterId })
    if (opts.chapterName) this.setData({ fromChapterName: safeDecodeURIComponent(opts.chapterName, '') })
  },

  async onShow() {
    this._pageVisible = true
    const activeSyncSeq = (this._activeSyncSeq || 0) + 1
    this._activeSyncSeq = activeSyncSeq
    this._syncThemeFromStorage()

    // Capture any action that timed out previously. It will be retried after the
    // local snapshot has restored the first frame, so network work never blocks UI.
    const pendingSync = this._getPendingPomodoroSync()

    // Make the page visible immediately. Active-session reconciliation must not
    // block the first frame behind a network request.
    if (!this.data.pageEntered) {
      this.setData({ pageEntered: true })
    }

    await recoverOnShow(this._showRecoveryOptions(activeSyncSeq), pendingSync)
  },

  _showRecoveryOptions(activeSyncSeq) {
    return {
      readStorage: (key, context) => this._safeGetPomodoroStorage(key, context),
      removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
      persistenceError: () => this._showPomodoroPersistenceError(),
      reconcileStart: () => this._reconcileUnknownStartAttempt(),
      isCurrent: () => this._pageVisible && activeSyncSeq === this._activeSyncSeq,
      consumeConflict: () => this._consumeAnyPomodoroTerminalConflict(),
      handleConflict: (sessionId, conflict) => this._handlePomodoroTerminalConflict(sessionId, conflict),
      showCompletion: completion => this._restoreCompletionView(completion),
      retryPending: () => this._retryPendingPomodoroSync(),
      loadStats: () => this.loadTodayStats(),
      deferStats: () => setTimeout(() => this.loadTodayStats(), 200),
      isNavigatingToStats: () => this._navigatingToStats,
      resetNavigation: () => { this._navigatingToStats = false },
      clearConfirmation: () => this._clearRestoredConfirmation(),
      confirmSnapshot: () => this._confirmTimerSnapshot,
      isValidConfirmation: snapshot => this._isValidConfirmSnapshot(snapshot),
      restoreConfirmation: snapshot => this._restoreConfirmSnapshot(snapshot),
      recoverActive: pending => this._recoverActiveSession(pending, activeSyncSeq),
    }
  },

  _restoreCompletionView(completion) {
    const recovery = buildCompletionRecovery(completion, this.data, pomodoroTaskTypes)
    this._completionBreakSec = recovery.breakSec
    if (!this.data.showCelebration) wx.vibrateLong()
    this.setData(recovery.view)
  },

  _clearRestoredConfirmation() {
    this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'best-effort cleanup')
    this._confirmTimerSnapshot = null
    this._timerState.endConfirmMode = ''
    this.setData({ showEndConfirm: false })
  },

  _restoreConfirmSnapshot(snapshot) {
    return restoreConfirmSnapshot({
      nextSequence: () => {
        this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
        return this._confirmActionSeq
      },
      setSnapshot: value => { this._confirmTimerSnapshot = value },
      sessionStartTime: () => this._timerState.sessionStartTime,
      applyTimer: patch => Object.assign(this._timerState, patch),
      buildView: (mode, value) => buildEndConfirmViewModel(mode, value),
      applyView: patch => this.setData(patch),
      nextTick: callback => wx.nextTick(callback),
      draw: value => {
        this._initCanvas(true)
        this.drawRing(value.totalSec, value.phase === 'break')
      },
      pause: (sessionId, openedAt) => this._postPauseWithRetry(sessionId, openedAt),
      currentSequence: () => this._confirmActionSeq,
      isConfirmVisible: () => this.data.showEndConfirm,
      persist: value => this._safeSetPomodoroStorage('pomodoro_confirm_pause', value, 'confirm snapshot refresh'),
      deferStats: () => setTimeout(() => this.loadTodayStats(), 200),
    }, snapshot)
  },

  _recoverActiveSession(pendingSync, activeSyncSeq) {
    return recoverActiveSession({
      readCached: () => this._getCachedActiveSession(),
      isStorageError: value => this._isPomodoroStorageError(value),
      persistenceError: () => this._showPomodoroPersistenceError(),
      canLightSync: session => this._canLightSyncActive(session),
      syncLight: (session, persist) => this._syncActiveSessionLight(session, persist),
      restoreSession: session => this._restoreSession(session),
      isRunning: () => this.data.phase === PHASE.RUNNING,
      sessionId: () => this._timerState.sessionId,
      restoreBreak: () => this._restoreBreak(),
      retryPending: () => this._retryPendingPomodoroSync(),
      consumeConflict: () => this._consumeAnyPomodoroTerminalConflict(),
      handleConflict: (sessionId, conflict) => this._handlePomodoroTerminalConflict(sessionId, conflict),
      deferStats: () => setTimeout(() => this.loadTodayStats(), 200),
      fetchActive: () => this._fetchActiveSession(),
      hasPendingTerminal: (sessionId, actions) => this._hasPendingPomodoroAction(sessionId, actions),
      removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
      clearTimer: () => this._clearTimer(),
      resetIdle: () => this._resetToIdle(),
      isCurrent: () => this._pageVisible && activeSyncSeq === this._activeSyncSeq,
    }, pendingSync)
  },

  onHide() {
    this._pageVisible = false
    this._activeSyncSeq = (this._activeSyncSeq || 0) + 1
    this._startRequestSeq = (this._startRequestSeq || 0) + 1
    this._clearPendingPomodoroSyncRetryTimer()

    const persistence = this._hidePersistenceOptions()
    cancelUnknownStartOnHide(persistence)

    // Native 2D canvas backing surfaces may be recreated while a Mini Program page
    // is hidden. Never reuse a context across onHide/onShow, even when selector
    // initialization had already completed successfully.
    this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
    this._canvasInitPending = false
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null
    this._pendingDraw = null
    this._lastDrawnProgress = undefined
    this._lastDrawnIsBreak = undefined
    if (this.data.ringCanvasPaintReady) this.setData({ ringCanvasPaintReady: false })

    // A start ceremony is UI-only. Leaving the page cancels it so its delayed
    // callback cannot create a hidden server session.
    if (this.data.phase === PHASE.CEREMONY) this.setData({ phase: PHASE.IDLE })

    persistSessionOnHide(persistence)
    // Single cleanup call — _clearTimer already clears free interval too
    this._clearTimer()
  },

  _hidePersistenceOptions() {
    return {
      readStorage: (key, context) => this._safeGetPomodoroStorage(key, context),
      writeStorage: (key, value, context) => this._safeSetPomodoroStorage(key, value, context),
      view: () => this.data,
      timer: () => this._timerState,
      confirmSnapshot: () => this._confirmTimerSnapshot,
      now: () => api.now(),
    }
  },

  onUnload() {
    this._pageVisible = false
    this._activeSyncSeq = (this._activeSyncSeq || 0) + 1
    this._startRequestSeq = (this._startRequestSeq || 0) + 1
    this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
    this._canvasInitPending = false
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null
    this._clearTimer()
    this._releasePauseToggleLock()
    this._clearPendingPomodoroSyncRetryTimer(true)
    this._getStatsController().invalidate()
    this._unregisterNetworkStatusListener()
    this._getThemeController().clearSwitchTimer()
    // Do not overwrite the native navigation bar with a blue fallback here.
    // That global write survived page teardown and appeared as a blue rectangle
    // before the next pomodoro theme frame was applied on re-entry.
    try {
      if (wx.setBackgroundColor) {
        wx.setBackgroundColor({
          backgroundColor: '#F4F4EE',
          backgroundColorTop: '#F4F4EE',
          backgroundColorBottom: '#F4F4EE',
        })
      }
      if (wx.setBackgroundTextStyle) wx.setBackgroundTextStyle({ textStyle: 'dark' })
    } catch (_) {}
  },

  _getSyncRetryController() {
    if (!this._syncRetryController) {
      this._syncRetryController = createSyncRetryController({
        setTimeout: (fn, delay) => setTimeout(fn, delay),
        clearTimeout: timer => clearTimeout(timer),
        isVisible: () => this._pageVisible,
        hasPending: () => !!this._getPendingPomodoroSync(),
        retry: () => this._retryPendingPomodoroSync(),
        warn: (message, error) => console.warn(message, error),
        consumeConflict: () => this._consumeAnyPomodoroTerminalConflict(),
        handleConflict: (sessionId, conflict) => this._handlePomodoroTerminalConflict(sessionId, conflict),
        loadStats: () => this.loadTodayStats(),
        canListen: () => typeof wx.onNetworkStatusChange === 'function' &&
          typeof wx.offNetworkStatusChange === 'function',
        onNetworkStatusChange: handler => wx.onNetworkStatusChange(handler),
        offNetworkStatusChange: handler => {
          if (typeof wx.offNetworkStatusChange === 'function') wx.offNetworkStatusChange(handler)
        },
      })
    }
    return this._syncRetryController
  },

  _registerNetworkStatusListener() {
    this._getSyncRetryController().register()
  },

  _unregisterNetworkStatusListener() {
    if (this._syncRetryController) this._syncRetryController.unregister()
  },

  _isRetryablePomodoroSyncError(error) {
    return isRetryableSyncError(error)
  },

  _clearPendingPomodoroSyncRetryTimer(resetAttempt = false) {
    if (this._syncRetryController) this._syncRetryController.clear(resetAttempt)
  },

  _schedulePendingPomodoroSyncRetry(error) {
    this._getSyncRetryController().schedule(error)
  },

  _releasePauseToggleLock() {
    this._getPauseToggleController().release()
  },

  _getPauseToggleController() {
    if (!this._pauseToggleController) {
      this._pauseToggleController = createPauseToggleController({
        cooldownMs: POMODORO_PAUSE_TOGGLE_COOLDOWN_MS,
        setTimeout: (callback, delay) => setTimeout(callback, delay),
        clearTimeout: id => clearTimeout(id),
        phase: () => this.data.phase,
        runningPhase: PHASE.RUNNING,
        sessionId: () => this._timerState.sessionId,
        actionLoading: () => this.data.actionLoading,
        showEndConfirm: () => this.data.showEndConfirm,
        isFreeTimer: () => this.data.isFreeTimer,
        isPaused: () => this.data.isPaused,
        pauseFree: () => this._pauseFreeTimer(),
        resumeFree: () => this._resumeFreeTimer(),
        pauseCountdown: () => this._pauseSession(),
        resumeCountdown: () => this._resumeSession(),
      })
    }
    return this._pauseToggleController
  },

  _acquirePauseToggleLock() {
    return this._getPauseToggleController().acquire()
  },

  /* ==================== Subject Loading ==================== */

  async _loadSubjects() {
    // Local 24h cache: the pomodoro page only needs a stable subject list and
    // the backend invalidates its own cache on Admin subject writes.
    const cached = readSubjectCache()
    if (cached && cached.length > 0) {
      this._applySubjects(cached)
      return
    }

    this.setData({ subjectsLoading: true, subjectsError: '' })
    try {
      const rawTree = await api.get('/practice/subjects')
      const tree = filter408SubjectTree(rawTree)
      if (!tree || !Array.isArray(tree)) {
        throw new Error('科目数据格式错误')
      }
      const { choices } = buildSubjectChoices(tree)
      writeSubjectCache(choices)
      this._applySubjects(choices)
    } catch (e) {
      console.error('加载科目失败', e)
      this.setData({ subjectsLoading: false, subjectsError: '科目加载失败，请稍后重试' })
    }
  },

  _applySubjects(flat) {
    const { patches, leaves } = buildApplySubjectsPlan(flat, this.data)
    for (const patch of patches) {
      this.setData(patch)
    }
    if (patches.length > 1) {
      this._updateComputedFields()
    }
    this._migrateRunningStateCache(leaves)
  },

  _lookupSubjectIdByCode(code) {
    if (!code) return null
    const match = (this.data.subjects || []).find(s => s.code === code)
    return match ? match.id : null
  },

  _migrateRunningStateCache(subjects) {
    const stored = this._safeGetPomodoroStorage('pomodoro_running_state', 'migrate running snapshot')
    if (!stored.ok) return false
    const local = stored.value
    if (!local || local.selectedSubjectId || !local.selectedSubjectCode) return true
    const match = (subjects || []).find(s => s.code === local.selectedSubjectCode)
    if (match) {
      local.selectedSubjectId = match.id
      if (!local.selectedSubjectName) local.selectedSubjectName = match.name || ''
      return this._safeSetPomodoroStorage('pomodoro_running_state', local, 'running snapshot refresh')
    }
    // 无法映射的旧 code 缓存 → 安全清除，避免恢复出无科目会话
    return this._safeRemovePomodoroStorage('pomodoro_running_state', 'stale running snapshot')
  },

  /* ==================== UI Handlers ==================== */

  selectSubject(e) {
    const disabled = e.currentTarget.dataset.disabled
    if (disabled === true || disabled === 'true') return
    const id = parseInt(e.currentTarget.dataset.id, 10) || null
    const subject = findSubjectById(this.data.subjects, id)
    if (subject) {
      this.setData({
        selectedSubjectId: id,
        selectedSubject: subject,
        allocationMode: subject._isAggregate ? 'equal_408_core_v1' : 'single',
      })
      this._updateComputedFields()
    }
  },

  selectTaskType(e) {
    const type = pomodoroTaskTypes.normalize(String(e.currentTarget.dataset.type || ''))
    pomodoroTaskTypes.setSelected(type)
    this.setData({ selectedTaskType: type, selectedTaskTypeLabel: pomodoroTaskTypes.label(type) })
  },

  onExamTap() {
    if (!config.DEBUG_MODE) return
    this._debugTapCount++
    if (this._debugTapTimer) clearTimeout(this._debugTapTimer)
    if (this._debugTapCount >= 5) {
      this._debugTapCount = 0
      const next = !this.data.debugMode
      this.setData({ debugMode: next })
      wx.showToast({ title: next ? '开发模式已开启' : '开发模式已关闭', icon: 'none', duration: 1500 })
      if (!next && this.data.selectedPreset === 'debug') {
        this.setData({ selectedPreset: 'standard', workDuration: 25, breakDuration: 5 })
      }
    } else {
      this._debugTapTimer = setTimeout(() => { this._debugTapCount = 0 }, 1500)
    }
  },

  selectPreset(e) {
    const key = e.currentTarget.dataset.key
    if (key === 'debug') {
      this.setData({ selectedPreset: 'debug', showCustom: false, workDuration: 0, breakDuration: 0 })
      this._updateComputedFields()
      return
    }
    if (key === 'free') {
      this.setData({ selectedPreset: 'free', showCustom: false, workDuration: 0, breakDuration: 0 })
      this._updateComputedFields()
      return
    }
    const preset = PRESETS.find(p => p.key === key)
    this.setData({
      selectedPreset: key,
      showCustom: key === 'custom',
      workDuration: preset ? preset.work : 25,
      breakDuration: preset ? preset.break : 5,
    })
    this._updateComputedFields()
  },

  onWorkChange(e) {
    const v = Math.max(5, Math.min(120, parseInt(e.detail.value, 10) || 25))
    this.setData({ workDuration: v })
  },

  onBreakChange(e) {
    const v = Math.max(5, Math.min(120, parseInt(e.detail.value, 10) || 5))
    this.setData({ breakDuration: v })
  },

  /* ==================== Touch / Swipe ==================== */

  noop() {},
  onCustomAreaTouch() {},

  onTouchStart(e) {
    this._touchStartX = e.touches[0].clientX
  },

  onTouchEnd(e) {
    if (this.data.phase !== PHASE.IDLE) return
    const diff = e.changedTouches[0].clientX - this._touchStartX
    if (Math.abs(diff) < 50) return

    const keys = PRESETS.map(p => p.key)
    const idx = keys.indexOf(this.data.selectedPreset)
    if (diff < 0) {
      const next = (idx + 1) % keys.length
      this.selectPreset({ currentTarget: { dataset: { key: keys[next] } } })
    } else {
      const prev = (idx - 1 + keys.length) % keys.length
      this.selectPreset({ currentTarget: { dataset: { key: keys[prev] } } })
    }
  },

  _getUnknownStartController() {
    if (!this._unknownStartController) {
      this._unknownStartController = createUnknownStartController({
        page: this,
        storageKey: POMODORO_UNKNOWN_START_KEY,
        post: (path, payload) => api.post(path, payload),
        createClientStartId: () => api.createClientStartId(),
        now: () => api.now(),
        parseServerTime,
        buildAttempt: buildUnknownStartAttempt,
        buildPayload: buildUnknownStartPayload,
        matches: matchesUnknownStartAttempt,
        startCancellationAt,
        recordSession: (session, taskType) => pomodoroTaskTypes.recordSession(session, taskType),
        reconcile: attempt => this._reconcileUnknownStartAttempt(attempt),
      })
    }
    return this._unknownStartController
  },

  _reconcileUnknownStartAttempt(explicitAttempt) {
    return this._getUnknownStartController().reconcile(explicitAttempt)
  },

  _postPomodoroStartWithReconciliation(payload, startSeq) {
    return this._getUnknownStartController().postStart(payload, startSeq)
  },

  /* ==================== Start Ceremony ==================== */

  _getStartSessionController() {
    if (!this._startSessionController) {
      this._startSessionController = createStartSessionController({
        page: this,
        phases: PHASE,
        ceremonyDelayMs: 2500,
        debugCeremonyDelayMs: 1000,
        wait: ms => new Promise(resolve => setTimeout(resolve, ms)),
        showToast: payload => wx.showToast(payload),
        pomodoroTaskTypes,
      })
    }
    return this._startSessionController
  },

  startSession() {
    return this._getStartSessionController().start()
  },

  /* ==================== Free Timer ==================== */

  _startFreeSession(existingStartSeq) {
    return this._getStartSessionController().startFree(existingStartSeq)
  },

  _beginFreeTimer(session) {
    return this._getFreeTimerBeginController().begin(session)
  },

  _getFreeTimerBeginController() {
    if (!this._freeTimerBeginController) {
      this._freeTimerBeginController = createFreeTimerBeginController({
        parseServerTime,
        now: () => api.now(),
        maxMs: FREE_TIMER_MAX_MS,
        formatElapsedSec,
        clearTimer: () => this._clearTimer(),
        timer: () => this._timerState,
        runningPhase: PHASE.RUNNING,
        setData: data => this.setData(data),
        updateComputedFields: () => this._updateComputedFields(),
        autoFinishFreeTimer: () => this._autoFinishFreeTimer(),
        startFreeTimerInterval: () => this._startFreeTimerInterval(),
        nextTick: callback => wx.nextTick(callback),
        initCanvas: force => this._initCanvas(force),
        drawRing: (total, isBreak) => this.drawRing(total, isBreak),
      })
    }
    return this._freeTimerBeginController
  },

  _getCancelEndConfirmController() {
    if (!this._cancelEndConfirmController) {
      this._cancelEndConfirmController = createCancelEndConfirmController({
        isActionLoading: () => this.data.actionLoading,
        getEndConfirmMode: () => this._timerState.endConfirmMode,
        getConfirmTimerSnapshot: () => this._confirmTimerSnapshot,
        setConfirmTimerSnapshot: v => { this._confirmTimerSnapshot = v },
        now: () => api.now(),
        incrementConfirmActionSeq: () => { this._confirmActionSeq = (this._confirmActionSeq || 0) + 1 },
        isPaused: () => this.data.isPaused,
        applyTimerState: patch => Object.assign(this._timerState, patch),
        safeGetStorage: key => this._safeGetPomodoroStorage(key, 'cancel end confirm'),
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'cancel confirm resume adjustment'),
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        setPendingSync: (action, sessionId, now) => this._setPendingPomodoroSync(action, sessionId, now),
        setData: data => this.setData(data),
        setCountdownTotalSec: v => { this._countdownTotalSec = v },
        startTimer: (totalSec, opts) => this._startTimer(totalSec, opts),
        startFreeTimerInterval: () => this._startFreeTimerInterval(),
        restartFreeTimerInterval: () => this._restartFreeTimerInterval(),
        nextTick: callback => wx.nextTick(callback),
        initCanvas: force => this._initCanvas(force),
        drawRing: (total, isBreak) => this.drawRing(total, isBreak),
        redrawFreeRingAfterOverlay: () => this._redrawFreeRingAfterOverlay(),
        retryPendingSync: () => this._retryPendingPomodoroSync(),
        warn: msg => console.warn(msg),
      })
    }
    return this._cancelEndConfirmController
  },

  _getShowEndFreeConfirmController() {
    if (!this._showEndFreeConfirmController) {
      this._showEndFreeConfirmController = createShowEndFreeConfirmController({
        getSessionId: () => this._timerState.sessionId,
        isActionLoading: () => this.data.actionLoading,
        now: () => api.now(),
        isPaused: () => !!this.data.isPaused,
        getElapsedSec: () => this._timerState.elapsedSec,
        formatElapsedSec,
        incrementConfirmActionSeq: () => {
          this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
          return this._confirmActionSeq
        },
        getTotalPausedMs: () => this._timerState.totalPausedMs || 0,
        getPauseStartTime: () => this._timerState.pauseStartTime || null,
        getSessionStartTime: () => this._timerState.sessionStartTime,
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'free confirm snapshot'),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        setPendingSync: (action, sessionId, now) => this._setPendingPomodoroSync(action, sessionId, now),
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'free confirm rollback'),
        setConfirmTimerSnapshot: v => { this._confirmTimerSnapshot = v },
        clearFreeTimerInterval: () => this._clearFreeTimerInterval(),
        setTimerFields: patch => Object.assign(this._timerState, patch),
        setData: data => this.setData(data),
        postPauseWithRetry: snapshot =>
          this._postPauseWithRetry(this._timerState.sessionId, snapshot.openedAt)
            .then(() => {
              if (snapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
              snapshot.backendPauseDone = true
              this._confirmTimerSnapshot = snapshot
              this._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'confirm snapshot refresh')
            }),
        warn: (msg, e) => console.warn(msg, e),
      })
    }
    return this._showEndFreeConfirmController
  },

  _getPauseCountdownEndConfirmController() {
    if (!this._pauseCountdownEndConfirmController) {
      this._pauseCountdownEndConfirmController = createPauseCountdownEndConfirmController({
        getSessionId: () => this._timerState.sessionId,
        isActionLoading: () => this.data.actionLoading,
        now: () => api.now(),
        getCurrentTotalSec: () => this._getCurrentTotalSec(),
        getCountdownEndAt: () => this._countdownEndAt,
        getRemainingSec: () => this._timerState.remainingSec,
        isPaused: () => !!this.data.isPaused,
        getPhase: () => this.data.phase,
        incrementConfirmActionSeq: () => {
          this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
          return this._confirmActionSeq
        },
        getSessionStartTime: () => this._timerState.sessionStartTime,
        getTotalPausedMs: () => this._timerState.totalPausedMs || 0,
        getPauseStartTime: () => this._timerState.pauseStartTime || null,
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'countdown confirm snapshot'),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        setPendingSync: (action, sessionId, now) => this._setPendingPomodoroSync(action, sessionId, now),
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'countdown confirm rollback'),
        setConfirmTimerSnapshot: v => { this._confirmTimerSnapshot = v },
        clearTimer: () => this._clearTimer(),
        setCountdownEndAt: v => { this._countdownEndAt = v },
        formatCountdownDisplay: sec => this._formatCountdownDisplay(sec),
        setTimerFields: patch => Object.assign(this._timerState, patch),
        setData: data => this.setData(data),
        drawRing: (total, isBreak) => this.drawRing(total, isBreak),
        postPauseWithRetry: snapshot =>
          this._postPauseWithRetry(this._timerState.sessionId, snapshot.openedAt)
            .then(() => {
              if (snapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
              snapshot.backendPauseDone = true
              this._confirmTimerSnapshot = snapshot
              this._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'confirm snapshot refresh')
            }),
        warn: (msg, e) => console.warn(msg, e),
      })
    }
    return this._pauseCountdownEndConfirmController
  },

  _getConfirmInterruptCountdownController() {
    if (!this._confirmInterruptCountdownController) {
      this._confirmInterruptCountdownController = createConfirmInterruptCountdownController({
        getSessionId: () => this._timerState.sessionId,
        isActionLoading: () => this.data.actionLoading,
        getConfirmTimerSnapshot: () => this._confirmTimerSnapshot,
        getTotalPausedMs: () => this._timerState.totalPausedMs || 0,
        setTotalPausedMs: v => { this._timerState.totalPausedMs = v },
        now: () => api.now(),
        incrementConfirmActionSeq: () => { this._confirmActionSeq = (this._confirmActionSeq || 0) + 1 },
        setPendingSync: (action, sessionId, now) => this._setPendingPomodoroSync(action, sessionId, now),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        setData: data => this.setData(data),
        retryPendingSync: () => this._retryPendingPomodoroSync(),
        consumeTerminalConflict: (sessionId, action) => this._consumePomodoroTerminalConflict(sessionId, action),
        handleTerminalConflict: (sessionId, conflict) => this._handlePomodoroTerminalConflict(sessionId, conflict),
        showToast: toast => wx.showToast(toast),
        loadTodayStats: () => this.loadTodayStats(),
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
        setConfirmTimerSnapshot: v => { this._confirmTimerSnapshot = v },
        resetToIdle: () => this._resetToIdle(),
      })
    }
    return this._confirmInterruptCountdownController
  },

  _getResetToIdleController() {
    if (!this._resetToIdleController) {
      this._resetToIdleController = createResetToIdleController({
        clearFreeTimerInterval: () => this._clearFreeTimerInterval(),
        setConfirmTimerSnapshot: v => { this._confirmTimerSnapshot = v },
        invalidateCanvas: () => {
          this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
          this._canvasReady = false
          this._canvasInitPending = false
          this._ctx = null
          this._pendingDraw = null
          this._lastDrawnProgress = undefined
          this._lastDrawnIsBreak = undefined
          this._ringCache = null
        },
        resetTimerState: () => { this._timerState = this._createTimerState() },
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
        getSelectedTaskType: () => pomodoroTaskTypes.getSelected(),
        taskTypeLabel: type => pomodoroTaskTypes.label(type),
        idlePhase: () => PHASE.IDLE,
        setData: data => this.setData(data),
        setCompletionBreakSec: v => { this._completionBreakSec = v },
        updateComputedFields: () => this._updateComputedFields(),
      })
    }
    return this._resetToIdleController
  },

  _getUpdateFreeElapsedController() {
    if (!this._updateFreeElapsedController) {
      this._updateFreeElapsedController = createUpdateFreeElapsedController({
        isFreeTimer: () => this.data.isFreeTimer,
        showEndConfirm: () => this.data.showEndConfirm,
        isPaused: () => this.data.isPaused,
        getElapsedSec: () => this._timerState.elapsedSec,
        setData: data => this.setData(data),
        setFreeFriendlyText: v => { this._timerState.freeFriendlyText = v },
        getEffectiveFreeElapsedMs: () => this._getEffectiveFreeElapsedMs(),
        maxMs: () => FREE_TIMER_MAX_MS,
        setElapsedSec: v => { this._timerState.elapsedSec = v },
      })
    }
    return this._updateFreeElapsedController
  },

  _getBeginCountdownController() {
    if (!this._beginCountdownController) {
      this._beginCountdownController = createBeginCountdownController({
        parseServerTime,
        isDebugPreset: () => this.data.selectedPreset === 'debug',
        getWorkDurationMinutes: () => this.data.workDuration,
        now: () => api.now(),
        setTimerFields: patch => Object.assign(this._timerState, patch),
        runningPhase: () => PHASE.RUNNING,
        setData: data => this.setData(data),
        updateComputedFields: () => this._updateComputedFields(),
        onWorkComplete: () => this._onWorkComplete(),
        startTimer: (totalSec, opts) => this._startTimer(totalSec, opts),
      })
    }
    return this._beginCountdownController
  },

  _getPauseSessionController() {
    if (!this._pauseSessionController) {
      this._pauseSessionController = createPauseSessionController({
        getSessionId: () => this._timerState.sessionId,
        isActionLoading: () => this.data.actionLoading,
        now: () => api.now(),
        setPendingSync: (action, sid, now) => this._setPendingPomodoroSync(action, sid, now),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        clearTimer: () => this._clearTimer(),
        setPauseStartTime: v => { this._timerState.pauseStartTime = v },
        setData: data => this.setData(data),
        getTotalPausedMs: () => this._timerState.totalPausedMs || 0,
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'countdown pause snapshot'),
        retryPendingSync: () => this._retryPendingPomodoroSync(),
        showToast: toast => wx.showToast(toast),
      })
    }
    return this._pauseSessionController
  },

  _getResumeSessionController() {
    if (!this._resumeSessionController) {
      this._resumeSessionController = createResumeSessionController({
        getSessionStartTime: () => this._timerState.sessionStartTime,
        warn: (msg, val) => console.warn(msg, val),
        resetToIdle: () => this._resetToIdle(),
        getSessionId: () => this._timerState.sessionId,
        isActionLoading: () => this.data.actionLoading,
        now: () => api.now(),
        getPauseStartTime: () => this._timerState.pauseStartTime,
        getTotalPausedMs: () => this._timerState.totalPausedMs || 0,
        isDebugPreset: () => this.data.selectedPreset === 'debug',
        getWorkDurationMinutes: () => this.data.workDuration,
        setPendingSync: (action, sid, now) => this._setPendingPomodoroSync(action, sid, now),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'countdown resume adjustment'),
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'countdown resume snapshot'),
        setTimerFields: patch => Object.assign(this._timerState, patch),
        setData: data => this.setData(data),
        startTimer: (totalSec, opts) => this._startTimer(totalSec, opts),
        retryPendingSync: () => this._retryPendingPomodoroSync(),
        showToast: toast => wx.showToast(toast),
      })
    }
    return this._resumeSessionController
  },

  _getShowCountdownInterruptConfirmController() {
    if (!this._showCountdownInterruptConfirmController) {
      this._showCountdownInterruptConfirmController = createShowCountdownInterruptConfirmController({
        isActionLoading: () => this.data.actionLoading,
        pauseCountdown: () => this._pauseCountdownForEndConfirm(),
        getConfirmTimerSnapshot: () => this._confirmTimerSnapshot,
        setData: data => this.setData(data),
        nextTick: callback => wx.nextTick(callback),
        initCanvas: force => this._initCanvas(force),
        drawRing: (total, isBreak) => this.drawRing(total, isBreak),
      })
    }
    return this._showCountdownInterruptConfirmController
  },

  _getConfirmEndTimerController() {
    if (!this._confirmEndTimerController) {
      this._confirmEndTimerController = createConfirmEndTimerController({
        isActionLoading: () => this.data.actionLoading,
        getEndConfirmMode: () => this._timerState.endConfirmMode,
        confirmEndFreeTimer: () => this._confirmEndFreeTimer(),
        confirmInterruptCountdown: () => this._confirmInterruptCountdown(),
        warn: (msg, detail) => console.warn(msg, detail),
        getSessionId: () => this._timerState.sessionId,
        getSnapshotMode: () => this._confirmTimerSnapshot && this._confirmTimerSnapshot.mode,
        showToast: toast => wx.showToast(toast),
      })
    }
    return this._confirmEndTimerController
  },

  _getEndSessionController() {
    if (!this._endSessionController) {
      this._endSessionController = createEndSessionController({
        getSessionId: () => this._timerState.sessionId,
        clearTimer: () => this._clearTimer(),
        completeWithRetry: (sessionId, now) => this._completePomodoroWithRetry(sessionId, now),
        now: () => api.now(),
        consumeTerminalConflict: (sessionId, action) => this._consumePomodoroTerminalConflict(sessionId, action),
        handleTerminalConflict: (sessionId, conflict) => this._handlePomodoroTerminalConflict(sessionId, conflict),
        loadTodayStats: () => this.loadTodayStats(),
        resetToIdle: () => this._resetToIdle(),
      })
    }
    return this._endSessionController
  },

  _getPauseFreeTimerController() {
    if (!this._pauseFreeTimerController) {
      this._pauseFreeTimerController = createPauseFreeTimerController({
        getSessionId: () => this._timerState.sessionId,
        isActionLoading: () => this.data.actionLoading,
        now: () => api.now(),
        setPendingSync: (action, sid, now) => this._setPendingPomodoroSync(action, sid, now),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        updateFreeElapsed: () => this._updateFreeElapsed(),
        clearFreeTimerInterval: () => this._clearFreeTimerInterval(),
        setTimerFields: patch => Object.assign(this._timerState, patch),
        setData: data => this.setData(data),
        getElapsedSec: () => this._timerState.elapsedSec,
        getTotalPausedMs: () => this._timerState.totalPausedMs || 0,
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'free pause snapshot'),
        retryPendingSync: () => this._retryPendingPomodoroSync(),
        showToast: toast => wx.showToast(toast),
      })
    }
    return this._pauseFreeTimerController
  },

  _getResumeFreeTimerController() {
    if (!this._resumeFreeTimerController) {
      this._resumeFreeTimerController = createResumeFreeTimerController({
        getSessionId: () => this._timerState.sessionId,
        isActionLoading: () => this.data.actionLoading,
        now: () => api.now(),
        getPauseStartTime: () => this._timerState.pauseStartTime,
        getTotalPausedMs: () => this._timerState.totalPausedMs || 0,
        setPendingSync: (action, sid, now) => this._setPendingPomodoroSync(action, sid, now),
        showPersistenceError: () => this._showPomodoroPersistenceError(),
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'free resume adjustment'),
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'free resume snapshot'),
        setTimerFields: patch => Object.assign(this._timerState, patch),
        setData: data => this.setData(data),
        startFreeTimerInterval: () => this._startFreeTimerInterval(),
        retryPendingSync: () => this._retryPendingPomodoroSync(),
        showToast: toast => wx.showToast(toast),
      })
    }
    return this._resumeFreeTimerController
  },

  _getInterruptSessionController() {
    if (!this._interruptSessionController) {
      this._interruptSessionController = createInterruptSessionController({
        getSessionId: () => this._timerState.sessionId,
        isFreeTimer: () => this.data.isFreeTimer,
        showEndFreeConfirm: () => this._showEndFreeConfirm(),
        showCountdownInterruptConfirm: () => this._showCountdownInterruptConfirm(),
      })
    }
    return this._interruptSessionController
  },

  _getConfirmEndFreeTimerController() {
    if (!this._confirmEndFreeTimerController) {
      this._confirmEndFreeTimerController = createConfirmEndFreeTimerController({
        isActionLoading: () => this.data.actionLoading,
        getSessionId: () => this._timerState.sessionId,
        incrementConfirmActionSeq: () => { this._confirmActionSeq = (this._confirmActionSeq || 0) + 1 },
        setConfirmTimerSnapshot: v => { this._confirmTimerSnapshot = v },
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
        setData: data => this.setData(data),
        clearFreeTimerInterval: () => this._clearFreeTimerInterval(),
        completeFreeTimerSession: () => this._completeFreeTimerSession(),
      })
    }
    return this._confirmEndFreeTimerController
  },

  _getFreeTimerLimitController() {
    if (!this._freeTimerLimitController) {
      this._freeTimerLimitController = createFreeTimerLimitController({
        finalizing: () => this._freeTimerFinalizing,
        setFinalizing: value => { this._freeTimerFinalizing = value },
        autoFinish: () => this._autoFinishFreeTimer(),
        isFreeTimer: () => this.data.isFreeTimer,
        isPaused: () => this.data.isPaused,
        getEffectiveFreeElapsedMs: () => this._getEffectiveFreeElapsedMs(),
        maxMs: FREE_TIMER_MAX_MS,
        clearFreeTimerInterval: () => this._clearFreeTimerInterval(),
        formatElapsedSec,
        setElapsedSec: value => { this._timerState.elapsedSec = value },
        setData: data => this.setData(data),
        showToast: toast => wx.showToast(toast),
        getSessionId: () => this._timerState.sessionId,
        now: () => api.now(),
        completeWithRetry: (sessionId, clientActionAt) =>
          this._completePomodoroWithRetry(sessionId, clientActionAt),
        consumeTerminalConflict: (sessionId, requestedAction) =>
          this._consumePomodoroTerminalConflict(sessionId, requestedAction),
        handleTerminalConflict: (sessionId, conflict) =>
          this._handlePomodoroTerminalConflict(sessionId, conflict),
        loadTodayStats: () => this.loadTodayStats(),
        resetToIdle: () => this._resetToIdle(),
      })
    }
    return this._freeTimerLimitController
  },

  _updateFreeElapsed() {
    return this._getUpdateFreeElapsedController().update()
  },

  _getFreeTimerController() {
    if (!this._freeTimerController) {
      this._freeTimerController = createFreeTimerController({
        setTimeout: (fn, delay) => setTimeout(fn, delay),
        clearTimeout: timer => clearTimeout(timer),
        getElapsedMs: () => this._getEffectiveFreeElapsedMs(),
        isBlocked: () => this.data.isPaused || this.data.showEndConfirm,
        onTick: () => this._updateFreeElapsed(),
        shouldFinalize: () => this._checkFreeTimerLimitAndAutoEnd(),
      })
    }
    return this._freeTimerController
  },

  _clearFreeTimerInterval() {
    if (this._freeTimerController) this._freeTimerController.clear()
  },

  _startFreeTimerInterval() {
    return this._getFreeTimerController().start()
  },

  _restartFreeTimerInterval() {
    this._getFreeTimerController().restart()
  },

  async _pauseFreeTimer() {
    return this._getPauseFreeTimerController().pause()
  },

  async _resumeFreeTimer() {
    return this._getResumeFreeTimerController().resume()
  },

  async _reconcileAfterResumeError(e, sessionId) {
    return this._getResumeErrorController().reconcile(e, sessionId)
  },

  _getResumeErrorController() {
    if (!this._resumeErrorController) {
      this._resumeErrorController = createResumeErrorController({
        getActive: path => api.get(path),
        parseServerTime,
        showToast: toast => wx.showToast(toast),
        resetIdle: () => this._resetToIdle(),
        timer: () => this._timerState,
        isFreeTimer: () => this.data.isFreeTimer,
        mergeLocalPauseAdjustment: (sessionId, serverPausedMs) =>
          this._mergeLocalPauseAdjustment(sessionId, serverPausedMs),
        getEffectiveFreeElapsedMs: () => this._getEffectiveFreeElapsedMs(),
        formatElapsedSec,
        setData: data => this.setData(data),
        startFreeTimerInterval: () => this._startFreeTimerInterval(),
        removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
        now: () => api.now(),
        getCurrentTotalSec: () => this._getCurrentTotalSec(),
        startTimer: totalSec => this._startTimer(totalSec),
      })
    }
    return this._resumeErrorController
  },

  _isValidConfirmSnapshot(snapshot) {
    return isValidConfirmSnapshot(snapshot, api.now())
  },

  async _showEndFreeConfirm() {
    return this._getShowEndFreeConfirmController().show()
  },

  _getCurrentTotalSec() {
    if (this.data.phase === 'break') {
      return this.data.selectedPreset === 'debug'
        ? 5
        : Math.max(1, this.data.breakDuration * 60)
    }
    return this.data.selectedPreset === 'debug'
      ? 10
      : Math.max(1, this.data.workDuration * 60)
  },

  // Queue the confirm-window pause behind any earlier local mutations. This is
  // intentionally serialized with resume/complete/interrupt so a late /pause can
  // never arrive after the user has already chosen "continue".
  async _postPauseWithRetry(sessionId, clientActionAt) {
    return this._pauseSyncController().postPause(sessionId, clientActionAt)
  },

  _pauseSyncController() {
    return this._pauseSync || (
      this._pauseSync = createPomodoroPauseSyncController({
        setPendingPomodoroSync: (action, sessionId, clientActionAt) =>
          this._setPendingPomodoroSync(action, sessionId, clientActionAt),
        retryPendingPomodoroSync: () => this._retryPendingPomodoroSync(),
      })
    )
  },

  async _pauseCountdownForEndConfirm() {
    return this._getPauseCountdownEndConfirmController().pause()
  },

  async _showCountdownInterruptConfirm() {
    return this._getShowCountdownInterruptConfirmController().show()
  },

  async cancelEndConfirm() {
    return this._getCancelEndConfirmController().cancel()
  },

  async confirmEndTimer() {
    return this._getConfirmEndTimerController().confirm()
  },

  async _confirmEndFreeTimer() {
    return this._getConfirmEndFreeTimerController().confirm()
  },

  async _confirmInterruptCountdown() {
    return this._getConfirmInterruptCountdownController().confirm()
  },

  async endSession() {
    return this._getEndSessionController().end()
  },

  async interruptSession() {
    return this._getInterruptSessionController().interrupt()
  },

  /* ==================== Countdown Timer ==================== */

  _beginCountdown(session) {
    return this._getBeginCountdownController().begin(session)
  },

  togglePause() {
    this._getPauseToggleController().toggle()
  },

  async _pauseSession() {
    return this._getPauseSessionController().pause()
  },

  async _resumeSession() {
    return this._getResumeSessionController().resume()
  },

  _formatCountdownDisplay(sec) {
    return formatCountdownDisplay(sec)
  },

  /* ==================== Pending Network Sync ==================== */

  _safeGetPomodoroStorage(key, context = '') {
    return readStorage(wx, key, context)
  },

  _safeSetPomodoroStorage(key, value, context = '') {
    return writeStorage(wx, key, value, context)
  },

  _safeRemovePomodoroStorage(key, context = '') {
    return removeStorage(wx, key, context)
  },

  _showPomodoroPersistenceError() {
    wx.showToast({
      title: '本地存储异常，操作未执行，请清理空间后重试',
      icon: 'none',
      duration: 2500,
    })
  },

  _getPendingSyncStore() {
    if (!this._pendingSyncStore) {
      this._pendingSyncStore = createPendingSyncQueue({
        storage: {
          read: (key, context) => this._safeGetPomodoroStorage(key, context),
          write: (key, value, context) => this._safeSetPomodoroStorage(key, value, context),
          remove: (key, context) => this._safeRemovePomodoroStorage(key, context),
        },
        now: () => api.now(),
      })
    }
    return this._pendingSyncStore
  },

  _writePendingPomodoroSyncQueue(queue) {
    return this._getPendingSyncStore().write(queue)
  },

  _getPendingPomodoroSyncQueue() {
    return this._getPendingSyncStore().read()
  },

  _getPendingPomodoroSync() {
    return this._getPendingSyncStore().head()
  },

  _hasPendingPomodoroAction(sessionId, actions) {
    return this._getPendingSyncStore().has(sessionId, actions)
  },

  _setPendingPomodoroSync(action, sessionId, clientActionAt) {
    return this._getPendingSyncStore().enqueue(action, sessionId, clientActionAt)
  },

  _clearPendingPomodoroSync(expected) {
    return this._getPendingSyncStore().clear(expected)
  },

  _updatePendingPomodoroSync(expected, patch) {
    return this._getPendingSyncStore().update(expected, patch)
  },

  _dropPendingPomodoroSessionActions(sessionId) {
    const queue = this._getPendingPomodoroSyncQueue()
    if (queue === null) return false
    const persisted = this._writePendingPomodoroSyncQueue(
      queue.filter(item => item.sessionId !== sessionId)
    )
    if (!persisted) return false

    // Also remove stale per-session optimistic snapshots. Never touch a newer
    // session's cache when reconciliation discovers an old cross-device row.
    const staleSnapshotKeys = ['pomodoro_pause', 'pomodoro_free_pause', 'pomodoro_pause_adjustment']
    for (var keyIndex = 0; keyIndex < staleSnapshotKeys.length; keyIndex += 1) {
      const key = staleSnapshotKeys[keyIndex]
      const stored = this._safeGetPomodoroStorage(key, 'drop reconciled session snapshot')
      if (!stored.ok) return false
      if (stored.value && stored.value.sessionId === sessionId) {
        if (!this._safeRemovePomodoroStorage(key, 'drop reconciled session snapshot')) return false
      }
    }
    const running = this._safeGetPomodoroStorage('pomodoro_running_state', 'drop reconciled running snapshot')
    if (!running.ok) return false
    if (running.value && running.value.sessionId === sessionId) {
      if (!this._safeRemovePomodoroStorage('pomodoro_running_state', 'drop reconciled running snapshot')) return false
    }
    return true
  },

  _isPomodoroStorageError(value) {
    return conflictState.isStorageConflict(value)
  },

  _getTerminalConflictController() {
    if (!this._terminalConflictController) {
      this._terminalConflictController = createTerminalConflictController({
        storageKey: POMODORO_TERMINAL_CONFLICT_KEY,
        getStorage: (key, context) => this._safeGetPomodoroStorage(key, context),
        setStorage: (key, value, context) => this._safeSetPomodoroStorage(key, value, context),
        removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
        now: () => api.now(),
        createConflict: conflictState.createTerminalConflict,
        isValidConflict: conflictState.isValidTerminalConflict,
        matchesConflict: conflictState.matchesTerminalConflict,
        isStorageConflict: value => conflictState.isStorageConflict(value),
        handleTerminalConflict,
        dropSessionActions: sessionId => this._dropPendingPomodoroSessionActions(sessionId),
        persistenceError: () => this._showPomodoroPersistenceError(),
        getCompletionBreakSec: () => this._completionBreakSec,
        setCompletionBreakSec: value => { this._completionBreakSec = value },
        clearTimer: () => this._clearTimer(),
        setData: data => this.setData(data),
        resetIdle: () => this._resetToIdle(),
        showToast: toast => wx.showToast(toast),
        loadStats: () => this.loadTodayStats(),
      })
    }
    return this._terminalConflictController
  },

  _recordPomodoroTerminalConflict(sessionId, requestedAction, serverStatus) {
    return this._getTerminalConflictController().record(
      sessionId,
      requestedAction,
      serverStatus
    )
  },

  _readPomodoroTerminalConflict() {
    return this._getTerminalConflictController().read()
  },

  _consumePomodoroTerminalConflict(sessionId, requestedAction) {
    return this._getTerminalConflictController().consume(sessionId, requestedAction)
  },

  _consumeAnyPomodoroTerminalConflict() {
    return this._getTerminalConflictController().consumeAny()
  },

  _ackPomodoroTerminalConflict(conflict) {
    return this._getTerminalConflictController().ack(conflict)
  },

  _handlePomodoroTerminalConflict(sessionId, conflict) {
    return this._getTerminalConflictController().handle(sessionId, conflict)
  },

  _getPendingSyncController() {
    if (!this._pendingSyncController) {
      this._pendingSyncController = createPendingSyncController({
        getQueue: () => this._getPendingPomodoroSyncQueue(),
        clearPending: expected => this._clearPendingPomodoroSync(expected),
        updatePending: (expected, patch) => this._updatePendingPomodoroSync(expected, patch),
        enqueue: (action, sessionId, clientActionAt) => (
          this._setPendingPomodoroSync(action, sessionId, clientActionAt)
        ),
        hasPending: (sessionId, action) => this._hasPendingPomodoroAction(sessionId, action),
        canReconcile: error => canReconcilePendingSync(error),
        decideReconciliation: (pending, error, active) => (
          decidePendingSyncReconciliation(pending, error, active)
        ),
        formatClientActionAt: timestamp => {
          try {
            return new Date(timestamp).toISOString()
          } catch (_) {
            return null
          }
        },
        post: (path, body) => api.post(path, body),
        getActive: () => api.get('/pomodoro/active'),
        now: () => api.now(),
        isVisible: () => this._pageVisible,
        restoreSession: active => this._restoreSession(active),
        maybeClearAdjustment: sessionId => this._maybeClearLocalPauseAdjustment(sessionId),
        dropSessionActions: sessionId => this._dropPendingPomodoroSessionActions(sessionId),
        getStorage: (key, context) => this._safeGetPomodoroStorage(key, context),
        removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
        setCompletionBreakSec: value => { this._completionBreakSec = value },
        setData: data => this.setData(data),
        recordTerminalConflict: (sessionId, action, status) => (
          this._recordPomodoroTerminalConflict(sessionId, action, status)
        ),
        readConflict: () => this._readPomodoroTerminalConflict(),
        isStorageConflict: value => this._isPomodoroStorageError(value),
        clearRetryTimer: reset => this._clearPendingPomodoroSyncRetryTimer(reset),
        scheduleRetry: error => this._schedulePendingPomodoroSyncRetry(error),
        persistenceError: () => this._showPomodoroPersistenceError(),
        logError: (...args) => console.error(...args),
      })
    }
    return this._pendingSyncController
  },

  _reconcilePendingPomodoroSyncFailure(pending, error) {
    return this._getPendingSyncController().reconcileFailure(pending, error)
  },

  _retryPendingPomodoroSync() {
    return this._getPendingSyncController().drain()
  },

  _completePomodoroWithRetry(sessionId, clientActionAt) {
    return this._getPendingSyncController().complete(sessionId, clientActionAt)
  },

  _interruptPomodoroWithRetry(sessionId, clientActionAt) {
    return this._getPendingSyncController().interrupt(sessionId, clientActionAt)
  },

  /* ==================== Local Pause Adjustment ==================== */

  _pauseAdjustmentStorage() {
    return {
      read: (key, context) => this._safeGetPomodoroStorage(key, context),
      remove: (key, context) => this._safeRemovePomodoroStorage(key, context),
    }
  },

  _clearLocalPauseAdjustment(sessionId) {
    return clearLocalPauseAdjustment(this._pauseAdjustmentStorage(), sessionId)
  },

  _maybeClearLocalPauseAdjustment(sessionId) {
    if (this._hasPendingPomodoroAction(sessionId, ['pause', 'resume'])) return false
    return this._clearLocalPauseAdjustment(sessionId)
  },

  _getLocalPauseAdjustment(sessionId, failClosed = false) {
    return getLocalPauseAdjustment(this._pauseAdjustmentStorage(), sessionId, failClosed)
  },

  _mergeLocalPauseAdjustment(sessionId, serverPausedMs, failClosed = false) {
    return mergeLocalPauseAdjustment(this._pauseAdjustmentStorage(), sessionId, serverPausedMs, failClosed)
  },

  /* ==================== Free Timer Display Offset ==================== */

  _getFreeElapsedMs(now) {
    return this._getFreeElapsedController().getElapsedMs(now)
  },

  _getEffectiveFreeElapsedMs(now) {
    return this._getFreeElapsedController().getEffectiveElapsedMs(now)
  },

  _getFreeElapsedController() {
    if (!this._freeElapsedController) {
      this._freeElapsedController = createFreeElapsedController({
        now: () => api.now(),
        getSessionId: () => this._timerState.sessionId,
        getSessionStartTime: () => this._timerState.sessionStartTime,
        getTotalPausedMs: () => this._timerState.totalPausedMs,
        mergeLocalPauseAdjustment: (sessionId, totalPausedMs) =>
          this._mergeLocalPauseAdjustment(sessionId, totalPausedMs),
      })
    }
    return this._freeElapsedController
  },

  _checkFreeTimerLimitAndAutoEnd() {
    return this._getFreeTimerLimitController().check()
  },

  async _autoFinishFreeTimer() {
    return this._getFreeTimerLimitController().autoFinish()
  },

  async _completeFreeTimerSession() {
    return this._getFreeTimerLimitController().complete()
  },

  _getEffectivePausedMsFromSession(session) {
    return buildEffectivePausedMs(session, {
      parseServerTime,
      now: () => api.now(),
      mergeLocalAdjustment: (sessionId, ms) => this._mergeLocalPauseAdjustment(sessionId, ms),
    })
  },

  _startTimer(totalSec, options = {}) {
    return this._getStartTimerController().start(totalSec, options)
  },
  _clearTimer() {
    if (this._timerController) {
      this._timerController.clear()
      this._timerController = null
    }
    this._clearFreeTimerInterval()
  },

  /* ==================== Work Complete ==================== */

  _showCompletionCelebration(sessionId, options) {
    return this._getCompletionCelebrationController().show(sessionId, options)
  },

  _getCompletionCelebrationController() {
    if (!this._completionCelebrationController) {
      this._completionCelebrationController = createCompletionCelebrationController({
        buildCompletionCelebration,
        data: () => this.data,
        mottoes: MOTTOES,
        nextCelebrationType: () => this._nextCelebrationType(),
        recordSession: (session, taskType) => pomodoroTaskTypes.recordSession(session, taskType),
        removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
        setStorage: (key, value, context) => this._safeSetPomodoroStorage(key, value, context),
        clearConfirmSnapshot: () => { this._confirmTimerSnapshot = null },
        timer: () => this._timerState,
        setCompletionBreakSec: value => { this._completionBreakSec = value },
        invalidateCanvas: () => {
          this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
          this._canvasInitPending = false
          this._canvasReady = false
          this._ctx = null
          this._ringCache = null
          this._pendingDraw = null
        },
        setData: data => this.setData(data),
      })
    }
    return this._completionCelebrationController
  },

  async _onWorkComplete() {
    return this._getWorkCompleteController().complete()
  },

  _getWorkCompleteController() {
    if (!this._workCompleteController) {
      this._workCompleteController = createWorkCompleteController({
        timer: () => this._timerState,
        resetIdle: () => this._resetToIdle(),
        now: () => api.now(),
        clearTimer: () => this._clearTimer(),
        vibrateLong: () => wx.vibrateLong(),
        completeWithRetry: (sessionId, completedAt) => this._completePomodoroWithRetry(sessionId, completedAt),
        consumeTerminalConflict: (sessionId, action) => this._consumePomodoroTerminalConflict(sessionId, action),
        handleTerminalConflict: (sessionId, conflict) => this._handlePomodoroTerminalConflict(sessionId, conflict),
        loadStats: () => this.loadTodayStats(),
        showToast: toast => wx.showToast(toast),
        showCompletionCelebration: sessionId => this._showCompletionCelebration(sessionId),
      })
    }
    return this._workCompleteController
  },

  dismissCelebration() {
    return this._getCelebrationDismissController().dismiss()
  },

  _getCelebrationDismissController() {
    if (!this._celebrationDismissController) {
      this._celebrationDismissController = createCelebrationDismissController({
        getStorage: (key, context) => this._safeGetPomodoroStorage(key, context),
        removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
        resolveBreakSec,
        getCompletionBreakSec: () => this._completionBreakSec,
        setCompletionBreakSec: value => { this._completionBreakSec = value },
        view: () => this.data,
        setData: data => this.setData(data),
        persistenceError: () => this._showPomodoroPersistenceError(),
        startBreak: breakSec => this._startBreak(breakSec),
        resetIdle: () => this._resetToIdle(),
      })
    }
    return this._celebrationDismissController
  },

  _getStartBreakController() {
    if (!this._startBreakController) {
      this._startBreakController = createStartBreakController({
        now: () => api.now(),
        safeSetStorage: (key, value) => this._safeSetPomodoroStorage(key, value, 'break snapshot'),
        safeRemoveStorage: key => this._safeRemovePomodoroStorage(key, 'best-effort cleanup'),
        setTimerFields: patch => Object.assign(this._timerState, patch),
        formatCountdownDisplay: sec => this._formatCountdownDisplay(sec),
        breakPhase: () => PHASE.BREAK,
        setData: data => this.setData(data),
        clearTimer: () => this._clearTimer(),
        initCanvas: force => this._initCanvas(force),
        setCountdownTotalSec: value => { this._countdownTotalSec = value },
        setCountdownEndAt: value => { this._countdownEndAt = value },
        getCountdownEndAt: () => this._countdownEndAt,
        getRemainingSec: () => this._timerState.remainingSec,
        getProgress: () => this._timerState.progress,
        drawRing: (total, isBreak) => this.drawRing(total, isBreak),
        resetToIdle: () => this._resetToIdle(),
        getTimerController: () => this._timerController,
        setTimerController: controller => { this._timerController = controller },
        setTimeout: (fn, delay) => setTimeout(fn, delay),
        clearTimeout: timer => clearTimeout(timer),
        clearInterval: timer => clearInterval(timer),
      })
    }
    return this._startBreakController
  },

  _getStartTimerController() {
    if (!this._startTimerController) {
      this._startTimerController = createStartTimerController({
        clearTimer: () => this._clearTimer(),
        initCanvas: force => this._initCanvas(force),
        setTimeout: (fn, delay) => setTimeout(fn, delay),
        clearTimeout: timer => clearTimeout(timer),
        clearInterval: timer => clearInterval(timer),
        setTimerController: controller => { this._timerController = controller },
        getRemainingSec: () => this._timerState.remainingSec,
        formatCountdownDisplay: sec => this._formatCountdownDisplay(sec),
        now: () => api.now(),
        setCountdownTotalSec: value => { this._countdownTotalSec = value },
        setCountdownEndAt: value => { this._countdownEndAt = value },
        setTimerFields: patch => Object.assign(this._timerState, patch),
        setData: data => this.setData(data),
        isPaused: () => this.data.isPaused,
        showEndConfirm: () => this.data.showEndConfirm,
        getCountdownEndAt: () => this._countdownEndAt,
        getProgress: () => this._timerState.progress,
        drawRing: (total, isBreak) => this.drawRing(total, isBreak),
        isBreakPhase: () => this.data.phase === 'break',
        onWorkComplete: () => this._onWorkComplete(),
      })
    }
    return this._startTimerController
  },

  /* ==================== Break Timer ==================== */

  _startBreak(totalSec, options = {}) {
    return this._getStartBreakController().start(totalSec, options)
  },
  skipBreak() {
    this._getSkipBreakController().skip()
  },

  _getSkipBreakController() {
    if (!this._skipBreakController) {
      this._skipBreakController = createSkipBreakController({
        clearTimer: () => this._clearTimer(),
        removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
        resetIdle: () => this._resetToIdle(),
      })
    }
    return this._skipBreakController
  },

  /* ==================== Session Restore ==================== */

  _canLightSyncActive(active) {
    return this._getActiveSyncController().canLightSync(active)
  },

  _syncActiveSessionLight(active, failClosed = false) {
    return this._getActiveSyncController().syncLight(active, failClosed)
  },

  _getActiveSyncController() {
    if (!this._activeSyncController) {
      this._activeSyncController = createActiveSyncController({
        now: () => api.now(),
        view: () => this.data,
        timer: () => this._timerState,
        runningPhase: PHASE.RUNNING,
        parseServerTime,
        setData: data => this.setData(data),
        updateComputedFields: () => this._updateComputedFields(),
        mergeLocalPauseAdjustment: (sessionId, serverPausedMs, failClosed) =>
          this._mergeLocalPauseAdjustment(sessionId, serverPausedMs, failClosed),
        persistenceError: () => this._showPomodoroPersistenceError(),
        canvasReady: () => !!this._canvasReady,
        ctx: () => this._ctx,
        nextTick: callback => wx.nextTick(callback),
        isPageVisible: () => this._pageVisible,
        initCanvas: force => this._initCanvas(force),
        drawRing: (total, isBreak) => this.drawRing(total, isBreak),
        maxMs: FREE_TIMER_MAX_MS,
        formatElapsedSec,
        autoFinishFreeTimer: () => this._autoFinishFreeTimer(),
        startFreeTimerInterval: () => this._startFreeTimerInterval(),
        clearTimer: () => this._clearTimer(),
        onWorkComplete: () => this._onWorkComplete(),
        startTimer: (totalSec, timerOptions) => this._startTimer(totalSec, timerOptions),
      })
    }
    return this._activeSyncController
  },

  _buildCachedActiveSession(local) {
    // An active session can remain paused for days. Do not silently discard its
    // only offline recovery snapshot on a fixed wall-clock TTL; the server's
    // terminal/active state is authoritative and clears this cache when reachable.
    return buildCachedActiveSession(local, (ms) => new Date(ms).toISOString())
  },

  _getCachedActiveSession() {
    const stored = this._safeGetPomodoroStorage('pomodoro_running_state', 'cached active session')
    if (!stored.ok) return { storageUnreadable: true }
    const local = stored.value
    const cached = this._buildCachedActiveSession(local)
    if (!cached && local && !this._safeRemovePomodoroStorage('pomodoro_running_state', 'stale cached active session')) {
      return { storageUnreadable: true }
    }
    return cached
  },

  async _fetchActiveSession() {
    const stored = this._safeGetPomodoroStorage('pomodoro_running_state', 'fetch active session')
    if (!stored.ok) return { storageUnreadable: true }
    const local = stored.value
    const cached = this._buildCachedActiveSession(local)
    try {
      const server = await api.get('/pomodoro/active')
      if (server) {
        if (!this._safeRemovePomodoroStorage('pomodoro_running_state', 'server active reconcile')) {
          return { storageUnreadable: true }
        }
        if (!this._hasPendingPomodoroAction(server.id, ['pause', 'resume'])) {
          if (!this._clearLocalPauseAdjustment(server.id)) return { storageUnreadable: true }
        }
        return server
      }
      if (!this._safeRemovePomodoroStorage('pomodoro_running_state', 'server no-active reconcile')) {
        return { storageUnreadable: true }
      }
      return null
    } catch (_) {
      // Weak/offline network: keep the timer usable from a fresh local snapshot.
      if (cached) return cached
    }
    if (!this._safeRemovePomodoroStorage('pomodoro_running_state', 'invalid cached active session')) {
      return { storageUnreadable: true }
    }
    return null
  },

  _restoreSession(session) {
    if (session.preset === 'free') {
      return this._restoreFreeSession(session)
    }
    if (!this._countdownSessionRestoreController) {
      this._countdownSessionRestoreController = createCountdownSessionRestoreController({
        page: this,
        now: () => api.now(),
        parseServerTime,
        resolvePausedMs,
        computeCountdownRestore,
        resolveRestoredSubject,
        formatCountdownDisplay,
        runningPhase: PHASE.RUNNING,
        pomodoroTaskTypes,
        nextTick: callback => wx.nextTick(callback),
        vibrateLong: () => wx.vibrateLong(),
        showToast: payload => wx.showToast(payload),
      })
    }
    return this._countdownSessionRestoreController.restore(session)
  },

  _restoreFreeSession(session) {
    if (!this._freeSessionRestoreController) {
      this._freeSessionRestoreController = createFreeSessionRestoreController({
        page: this,
        now: () => api.now(),
        parseServerTime,
        resolvePausedMs,
        computeFreeRestore,
        resolveRestoredSubject,
        formatElapsedSec,
        maxMs: FREE_TIMER_MAX_MS,
        runningPhase: PHASE.RUNNING,
        pomodoroTaskTypes,
        nextTick: callback => wx.nextTick(callback),
      })
    }
    return this._freeSessionRestoreController.restore(session)
  },

  _restoreBreak() {
    return this._getBreakRestoreController().restore()
  },

  _getBreakRestoreController() {
    if (!this._breakRestoreController) {
      this._breakRestoreController = createBreakRestoreController({
        getStorageSync: key => wx.getStorageSync(key),
        now: () => api.now(),
        removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
        resetIdle: () => this._resetToIdle(),
        startBreak: (totalSec, breakOptions) => this._startBreak(totalSec, breakOptions),
      })
    }
    return this._breakRestoreController
  },

  /* ==================== Progress Ring (Canvas 2D) ==================== */

  _redrawFreeRingAfterOverlay() {
    // Free timing uses a full ring (progress=1). cover-view dialogs temporarily
    // hide the native canvas; on real devices the canvas can come back blank.
    // Wait until setData has removed `hidden`, then rebuild the canvas so the
    // first frame is guaranteed to be painted instead of relying on stale ctx.
    this._timerState.progress = 1
    wx.nextTick(() => {
      if (this.data.showEndConfirm || !this.data.ringCanvasVisible) return
      this._initCanvas(true)
      this.drawRing(0, false)
    })
  },

  _initCanvas(force) {
    return this._getCanvasInitController().init(force)
  },

  _scheduleCanvasInit(retryCount, initSeq, previousRect) {
    return this._getCanvasInitController().schedule(retryCount, initSeq, previousRect)
  },

  _getCanvasInitController() {
    if (!this._canvasInitController) {
      this._canvasInitController = createCanvasInitController({
        canvasReady: () => this._canvasReady,
        getCtx: () => this._ctx,
        canvasInitPending: () => this._canvasInitPending,
        getCanvasInitSeq: () => this._canvasInitSeq,
        setCanvasInitSeq: value => { this._canvasInitSeq = value },
        setCanvasInitPending: value => { this._canvasInitPending = value },
        setCanvasReady: value => { this._canvasReady = value },
        setCtx: value => { this._ctx = value },
        setRingCache: value => { this._ringCache = value },
        ringCanvasPaintReady: () => this.data.ringCanvasPaintReady,
        setData: data => this.setData(data),
        setLastDrawnProgress: value => { this._lastDrawnProgress = value },
        setLastDrawnIsBreak: value => { this._lastDrawnIsBreak = value },
        setLastDrawnAt: value => { this._lastDrawnAt = value },
        maxRetries: () => CANVAS_INIT_MAX_RETRIES,
        nextTick: fn => wx.nextTick(fn),
        isPageVisible: () => this._pageVisible,
        createSelectorQuery: () => wx.createSelectorQuery().in(this),
        setTimeout: (fn, delay) => setTimeout(fn, delay),
        getWindowInfo: () => (wx.getWindowInfo ? wx.getWindowInfo() : {}),
        setDpr: value => { this._dpr = value },
        setCanvasSize: value => { this._canvasSize = value },
        getPendingDraw: () => this._pendingDraw,
        setPendingDraw: value => { this._pendingDraw = value },
        drawRing: (totalSec, isBreak) => this.drawRing(totalSec, isBreak),
      })
    }
    return this._canvasInitController
  },

  _buildRingCache(isBreak) {
    return buildRingCache(this._ctx, this._canvasSize, isBreak, this.data.isFreeTimer)
  },

  _getDrawRingController() {
    if (!this._drawRingController) {
      this._drawRingController = createDrawRingController({
        getCtx: () => this._ctx,
        setPendingDraw: value => { this._pendingDraw = value },
        isPageVisible: () => this._pageVisible,
        showEndConfirm: () => this.data.showEndConfirm,
        ringCanvasVisible: () => this.data.ringCanvasVisible,
        canvasInitPending: () => this._canvasInitPending,
        initCanvas: force => this._initCanvas(force),
        getProgress: () => this._timerState.progress,
        now: () => api.now(),
        getLastDrawnProgress: () => this._lastDrawnProgress,
        getLastDrawnIsBreak: () => this._lastDrawnIsBreak,
        getLastDrawnAt: () => this._lastDrawnAt,
        setLastDrawnProgress: v => { this._lastDrawnProgress = v },
        setLastDrawnIsBreak: v => { this._lastDrawnIsBreak = v },
        setLastDrawnAt: v => { this._lastDrawnAt = v },
        isFreeTimer: () => this.data.isFreeTimer,
        themeMode: () => this.data.themeMode,
        getRingCache: () => this._ringCache,
        setRingCache: v => { this._ringCache = v },
        buildRingCache: isBreak => this._buildRingCache(isBreak),
        ringCanvasPaintReady: () => this.data.ringCanvasPaintReady,
        setData: data => this.setData(data),
      })
    }
    return this._drawRingController
  },

  drawRing(totalSec, isBreak) {
    return this._getDrawRingController().draw(totalSec, isBreak)
  },

  _resetToIdle() {
    return this._getResetToIdleController().reset()
  },

  /* ==================== Stats ==================== */

  _getStatsController() {
    if (!this._statsController) {
      this._statsController = createStatsController({
        get: path => api.get(path),
        setTodayDurationSec: value => { this._timerState.todayDurationSec = value },
        setData: data => this.setData(data),
      })
    }
    return this._statsController
  },

  async loadTodayStats() {
    return this._getStatsController().load()
  },

  goStats() {
    this._navigatingToStats = true
    wx.navigateTo({ url: '/subpackages/productivity/pomodoro-stats/index' })
  },


  /* ==================== Theme ==================== */

  _getThemeController() {
    if (!this._themeController) {
      this._themeController = createThemeController({
        normalizeTheme: mode => pomodoroTheme.normalizeTheme(mode),
        getTheme: () => pomodoroTheme.getTheme(),
        setTheme: value => pomodoroTheme.setTheme(value),
        applyNativeTheme: value => pomodoroTheme.applyNativeTheme(value),
        getCurrentMode: () => this.data.themeMode,
        setData: (data, callback) => this.setData(data, callback),
        setTimeout: (callback, delay) => setTimeout(callback, delay),
        clearTimeout: id => clearTimeout(id),
        afterThemeApplied: () => {
          this._ringCache = null
          this._lastDrawnProgress = undefined
          this._lastDrawnIsBreak = undefined
          if ((this.data.phase === PHASE.RUNNING || this.data.phase === PHASE.BREAK) &&
              this.data.ringCanvasVisible && !this.data.showEndConfirm) {
            wx.nextTick(() => this.drawRing(this._getCurrentTotalSec(), this.data.phase === PHASE.BREAK))
          }
        },
      })
    }
    return this._themeController
  },

  _getThemeViewModel(mode) {
    return this._getThemeController().viewModel(mode)
  },

  _syncThemeFromStorage() {
    return this._getThemeController().sync()
  },

  _applyTheme(mode, persist, animate) {
    return this._getThemeController().apply(mode, persist, animate)
  },

  toggleTheme() {
    return this._getThemeController().toggle()
  },

  /* ==================== Font Size Toggle ==================== */

  cycleFontSize() {
    this._getFontSizeController().cycle()
  },

  _getFontSizeController() {
    if (!this._fontSizeController) {
      this._fontSizeController = createFontSizeController({
        getCurrentLevel: () => this.data.fontSizeLevel,
        setLevel: value => this.setData({ fontSizeLevel: value }),
        persist: value => wx.setStorageSync('pomodoro_font_size', value),
      })
    }
    return this._fontSizeController
  },

  _updateComputedFields() {
    const subj = this.data.selectedSubject
    this.setData({
      selectedSubjectLabel: subj ? subj.name : '',
      selectedSubjectIcon: subjectIconByCode(subj && subj.code),
      selectedAllocationLabel: subj && subj._isAggregate ? '四科均分' : '',
      selectedPresetLabel: this.presetLabel(this.data.selectedPreset),
    })
  },

  /* ==================== Utility ==================== */

  subjectLabel(key) {
    return this._getSubjectViewController().label(key)
  },

  _getSubjectViewController() {
    if (!this._subjectViewController) {
      this._subjectViewController = createSubjectViewController({
        getSubjects: () => this.data.subjects,
      })
    }
    return this._subjectViewController
  },

  subjectColor(key) {
    return this._getSubjectViewController().color()
  },


  presetLabel(key) {
    return this._getPresetViewController().label(key)
  },

  _getPresetViewController() {
    if (!this._presetViewController) {
      this._presetViewController = createPresetViewController({
        getPresets: () => PRESETS,
      })
    }
    return this._presetViewController
  },

  _nextCelebrationType() {
    return this._getCelebrationTypeController().next()
  },

  _getCelebrationTypeController() {
    if (!this._celebrationTypeController) {
      this._celebrationTypeController = createCelebrationTypeController({
        getIndex: () => wx.getStorageSync('pomodoro_anim_idx'),
        setIndex: value => wx.setStorageSync('pomodoro_anim_idx', value),
      })
    }
    return this._celebrationTypeController
  },

  getDateStr() {
    return this._getDateExamController().dateText()
  },

  _getExamDays() {
    return this._getDateExamController().examDays()
  },

  _getDateExamController() {
    if (!this._dateExamController) {
      this._dateExamController = createDateExamController({
        now: () => api.now(),
        getChinaWallParts,
        getChinaDayStartUtcMs,
        utc: parts => Date.UTC(parts.year, parts.month, parts.day),
        getUtcDay: ms => new Date(ms).getUTCDay(),
      })
    }
    return this._dateExamController
  },

})

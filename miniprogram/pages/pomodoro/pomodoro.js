const { PHASE, PRESETS, parseServerTime } = require('./utils/pomodoro-page-support')
const {
  buildSubjectLoadPageCapabilities,
  buildStartSessionPageCapabilities,
  buildFreeTimerBeginPageCapabilities,
  buildBeginCountdownPageCapabilities,
  buildPauseTogglePageCapabilities,
  buildStartTimerPageCapabilities,
  buildStartBreakPageCapabilities,
  buildSkipBreakPageCapabilities,
} = require('./utils/pomodoro-session-page-adapter')
const {
  buildPauseSessionPageCapabilities,
  buildResumeSessionPageCapabilities,
  buildPauseFreeTimerPageCapabilities,
  buildResumeFreeTimerPageCapabilities,
  buildInterruptSessionPageCapabilities,
  buildEndSessionPageCapabilities,
  buildResetToIdlePageCapabilities,
  buildUpdateFreeElapsedPageCapabilities,
  buildFreeTimerPageCapabilities,
  buildFreeTimerLimitPageCapabilities,
  buildFreeElapsedPageCapabilities,
  buildPomodoroPauseSyncPageCapabilities,
} = require('./utils/pomodoro-session-control-page-adapter')
const {
  buildCancelEndConfirmPageCapabilities,
  buildShowEndFreeConfirmPageCapabilities,
  buildPauseCountdownEndConfirmPageCapabilities,
  buildConfirmInterruptCountdownPageCapabilities,
  buildShowCountdownInterruptConfirmPageCapabilities,
  buildConfirmEndTimerPageCapabilities,
  buildConfirmEndFreeTimerPageCapabilities,
} = require('./utils/pomodoro-confirm-page-adapter')
const {
  buildCompletionCelebrationPageCapabilities,
  buildWorkCompletePageCapabilities,
  buildCelebrationDismissPageCapabilities,
  buildBreakRestorePageCapabilities,
  buildCelebrationTypePageCapabilities,
} = require('./utils/pomodoro-celebration-page-adapter')
const {
  buildSyncRetryPageCapabilities,
  buildUnknownStartPageCapabilities,
  buildResumeErrorPageCapabilities,
  buildPendingSyncQueuePageCapabilities,
  buildPomodoroSessionActionDropperPageCapabilities,
  buildTerminalConflictPageCapabilities,
  buildPendingSyncPageCapabilities,
  buildActiveSyncPageCapabilities,
  buildPomodoroActiveSessionReconcilerPageCapabilities,
  buildPomodoroRunningStateMigratorPageCapabilities,
} = require('./utils/pomodoro-recovery-page-adapter')
const {
  buildCanvasInitPageCapabilities,
  buildDrawRingPageCapabilities,
  buildStatsPageCapabilities,
  buildThemePageCapabilities,
  buildFontSizePageCapabilities,
  buildSubjectViewPageCapabilities,
  buildPresetViewPageCapabilities,
  buildDateExamPageCapabilities,
} = require('./utils/pomodoro-view-page-adapter')
const {
  buildCountdownSessionRestorePageCapabilities,
  buildFreeSessionRestorePageCapabilities,
} = require('./utils/pomodoro-restore-page-adapter')
const api = require('../../utils/api')
const { readStorage, writeStorage, removeStorage } = require('./utils/session-storage')
const { createPendingSyncQueue } = require('./utils/pending-sync-queue')
const { createSyncRetryController, isRetryableSyncError } = require('./utils/sync-retry-controller')
const { recoverActiveSession } = require('./utils/active-session-recovery')
const { buildCompletionRecovery } = require('./utils/completion-recovery')
const { restoreConfirmSnapshot } = require('./utils/confirm-recovery')
const { recoverOnShow } = require('./utils/show-recovery')
const { cancelUnknownStartOnHide, persistSessionOnHide } = require('./utils/hide-storage')

const config = require('../../config')
const { safeDecodeURIComponent } = require('./utils/route-params')
const pomodoroTheme = require('./utils/pomodoro-theme')
const { subjectIconByCode } = require('./utils/subject-options')
const {
  buildApplySubjectsPlan,
  createSubjectLoadController,
} = require('./utils/apply-subjects-controller')
const { buildEffectivePausedMs } = require('./utils/effective-paused-ms')

const { createFreeTimerController } = require('./utils/free-timer-controller')
const { buildRingCache } = require('./utils/ring-geometry')
const conflictState = require('./utils/terminal-conflict-state')

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
const { isValidConfirmSnapshot } = require('./utils/end-confirm-snapshot')
const { createActiveSyncController } = require('./utils/active-sync-controller')
const { createPauseToggleController } = require('./utils/pause-toggle-controller')
const { createPomodoroPauseSyncController } = require('./utils/pause-sync-controller')
const { createPomodoroSessionActionDropper } = require('./utils/session-action-dropper')
const { createPomodoroActiveSessionReconciler } = require('./utils/active-session-reconciler')
const { createPomodoroRunningStateMigrator } = require('./utils/running-state-migrator')
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

const {
  findSubjectById,
} = require('./utils/subject-selection')
const { formatCountdownDisplay } = require('./utils/timer-math')

const {
  getLocalPauseAdjustment,
  mergeLocalPauseAdjustment,
  clearLocalPauseAdjustment,
} = require('./utils/pause-adjustment')

const { buildEndConfirmViewModel } = require('./utils/end-confirm-view-model')

const { buildCachedActiveSession } = require('./utils/cached-session-builder')

const { pomodoroTaskTypes } = require('../../utils/storage')
 // 5 hours max for free timer

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
  _subjectLoadController: null,

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
      fromSubjectCode: String((opts && opts.subject_code) || ''), guestMode: Boolean(opts && String(opts.guest) === '1'),
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
    // First frame must not wait for session reconciliation.
    if (!this.data.pageEntered) this.setData({ pageEntered: true })
    if (this.data.guestMode) return

    const pendingSync = this._getPendingPomodoroSync()
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
      this._syncRetryController = createSyncRetryController(
        buildSyncRetryPageCapabilities(this, {})
      )
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
      this._pauseToggleController = createPauseToggleController(
        buildPauseTogglePageCapabilities(this, {})
      )
    }
    return this._pauseToggleController
  },

  _acquirePauseToggleLock() {
    return this._getPauseToggleController().acquire()
  },

  /* ==================== Subject Loading ==================== */

  _getSubjectLoadController() {
    if (!this._subjectLoadController) {
      this._subjectLoadController = createSubjectLoadController(
        buildSubjectLoadPageCapabilities(this, { api })
      )
    }
    return this._subjectLoadController
  },

  async _loadSubjects() {
    return this._getSubjectLoadController().load()
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
    return this.data.guestMode ? null : this._runningStateMigrator().migrate(subjects)
  },

  _runningStateMigrator() {
    if (!this._runningStateMigrationController) {
      this._runningStateMigrationController = createPomodoroRunningStateMigrator(
        buildPomodoroRunningStateMigratorPageCapabilities(this, {})
      )
    }
    return this._runningStateMigrationController
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
      this._unknownStartController = createUnknownStartController(
        buildUnknownStartPageCapabilities(this, { api })
      )
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
      this._startSessionController = createStartSessionController(
        buildStartSessionPageCapabilities(this, {})
      )
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
      this._freeTimerBeginController = createFreeTimerBeginController(
        buildFreeTimerBeginPageCapabilities(this, { api })
      )
    }
    return this._freeTimerBeginController
  },

  _getCancelEndConfirmController() {
    if (!this._cancelEndConfirmController) {
      this._cancelEndConfirmController = createCancelEndConfirmController(
        buildCancelEndConfirmPageCapabilities(this, { api })
      )
    }
    return this._cancelEndConfirmController
  },

  _getShowEndFreeConfirmController() {
    if (!this._showEndFreeConfirmController) {
      this._showEndFreeConfirmController = createShowEndFreeConfirmController(
        buildShowEndFreeConfirmPageCapabilities(this, { api })
      )
    }
    return this._showEndFreeConfirmController
  },

  _getPauseCountdownEndConfirmController() {
    if (!this._pauseCountdownEndConfirmController) {
      this._pauseCountdownEndConfirmController = createPauseCountdownEndConfirmController(
        buildPauseCountdownEndConfirmPageCapabilities(this, { api })
      )
    }
    return this._pauseCountdownEndConfirmController
  },

  _getConfirmInterruptCountdownController() {
    if (!this._confirmInterruptCountdownController) {
      this._confirmInterruptCountdownController = createConfirmInterruptCountdownController(
        buildConfirmInterruptCountdownPageCapabilities(this, { api })
      )
    }
    return this._confirmInterruptCountdownController
  },

  _getResetToIdleController() {
    if (!this._resetToIdleController) {
      this._resetToIdleController = createResetToIdleController(
        buildResetToIdlePageCapabilities(this, {})
      )
    }
    return this._resetToIdleController
  },

  _getUpdateFreeElapsedController() {
    if (!this._updateFreeElapsedController) {
      this._updateFreeElapsedController = createUpdateFreeElapsedController(
        buildUpdateFreeElapsedPageCapabilities(this, {})
      )
    }
    return this._updateFreeElapsedController
  },

  _getBeginCountdownController() {
    if (!this._beginCountdownController) {
      this._beginCountdownController = createBeginCountdownController(
        buildBeginCountdownPageCapabilities(this, { api })
      )
    }
    return this._beginCountdownController
  },

  _getPauseSessionController() {
    if (!this._pauseSessionController) {
      this._pauseSessionController = createPauseSessionController(
        buildPauseSessionPageCapabilities(this, { api })
      )
    }
    return this._pauseSessionController
  },

  _getResumeSessionController() {
    if (!this._resumeSessionController) {
      this._resumeSessionController = createResumeSessionController(
        buildResumeSessionPageCapabilities(this, { api })
      )
    }
    return this._resumeSessionController
  },

  _getShowCountdownInterruptConfirmController() {
    if (!this._showCountdownInterruptConfirmController) {
      this._showCountdownInterruptConfirmController = createShowCountdownInterruptConfirmController(
        buildShowCountdownInterruptConfirmPageCapabilities(this, {})
      )
    }
    return this._showCountdownInterruptConfirmController
  },

  _getConfirmEndTimerController() {
    if (!this._confirmEndTimerController) {
      this._confirmEndTimerController = createConfirmEndTimerController(
        buildConfirmEndTimerPageCapabilities(this, {})
      )
    }
    return this._confirmEndTimerController
  },

  _getEndSessionController() {
    if (!this._endSessionController) {
      this._endSessionController = createEndSessionController(
        buildEndSessionPageCapabilities(this, { api })
      )
    }
    return this._endSessionController
  },

  _getPauseFreeTimerController() {
    if (!this._pauseFreeTimerController) {
      this._pauseFreeTimerController = createPauseFreeTimerController(
        buildPauseFreeTimerPageCapabilities(this, { api })
      )
    }
    return this._pauseFreeTimerController
  },

  _getResumeFreeTimerController() {
    if (!this._resumeFreeTimerController) {
      this._resumeFreeTimerController = createResumeFreeTimerController(
        buildResumeFreeTimerPageCapabilities(this, { api })
      )
    }
    return this._resumeFreeTimerController
  },

  _getInterruptSessionController() {
    if (!this._interruptSessionController) {
      this._interruptSessionController = createInterruptSessionController(
        buildInterruptSessionPageCapabilities(this, {})
      )
    }
    return this._interruptSessionController
  },

  _getConfirmEndFreeTimerController() {
    if (!this._confirmEndFreeTimerController) {
      this._confirmEndFreeTimerController = createConfirmEndFreeTimerController(
        buildConfirmEndFreeTimerPageCapabilities(this, {})
      )
    }
    return this._confirmEndFreeTimerController
  },

  _getFreeTimerLimitController() {
    if (!this._freeTimerLimitController) {
      this._freeTimerLimitController = createFreeTimerLimitController(
        buildFreeTimerLimitPageCapabilities(this, { api })
      )
    }
    return this._freeTimerLimitController
  },

  _updateFreeElapsed() {
    return this._getUpdateFreeElapsedController().update()
  },

  _getFreeTimerController() {
    if (!this._freeTimerController) {
      this._freeTimerController = createFreeTimerController(
        buildFreeTimerPageCapabilities(this, {})
      )
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
      this._resumeErrorController = createResumeErrorController(
        buildResumeErrorPageCapabilities(this, { api })
      )
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
    if (!this._pauseSync) {
      this._pauseSync = createPomodoroPauseSyncController(
        buildPomodoroPauseSyncPageCapabilities(this, {})
      )
    }
    return this._pauseSync
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
      this._pendingSyncStore = createPendingSyncQueue(
        buildPendingSyncQueuePageCapabilities(this, { api })
      )
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
    return this._getSessionActionDropController().drop(sessionId)
  },

  _getSessionActionDropController() {
    if (!this._sessionActionDrop) {
      this._sessionActionDrop = createPomodoroSessionActionDropper(
        buildPomodoroSessionActionDropperPageCapabilities(this, {})
      )
    }
    return this._sessionActionDrop
  },

  _isPomodoroStorageError(value) {
    return conflictState.isStorageConflict(value)
  },

  _getTerminalConflictController() {
    if (!this._terminalConflictController) {
      this._terminalConflictController = createTerminalConflictController(
        buildTerminalConflictPageCapabilities(this, { api })
      )
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
      this._pendingSyncController = createPendingSyncController(
        buildPendingSyncPageCapabilities(this, { api })
      )
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
      this._freeElapsedController = createFreeElapsedController(
        buildFreeElapsedPageCapabilities(this, { api })
      )
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
      this._completionCelebrationController = createCompletionCelebrationController(
        buildCompletionCelebrationPageCapabilities(this, {})
      )
    }
    return this._completionCelebrationController
  },

  async _onWorkComplete() {
    return this._getWorkCompleteController().complete()
  },

  _getWorkCompleteController() {
    if (!this._workCompleteController) {
      this._workCompleteController = createWorkCompleteController(
        buildWorkCompletePageCapabilities(this, { api })
      )
    }
    return this._workCompleteController
  },

  dismissCelebration() {
    return this._getCelebrationDismissController().dismiss()
  },

  _getCelebrationDismissController() {
    if (!this._celebrationDismissController) {
      this._celebrationDismissController = createCelebrationDismissController(
        buildCelebrationDismissPageCapabilities(this, {})
      )
    }
    return this._celebrationDismissController
  },

  _getStartBreakController() {
    if (!this._startBreakController) {
      this._startBreakController = createStartBreakController(
        buildStartBreakPageCapabilities(this, { api })
      )
    }
    return this._startBreakController
  },

  _getStartTimerController() {
    if (!this._startTimerController) {
      this._startTimerController = createStartTimerController(
        buildStartTimerPageCapabilities(this, { api })
      )
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
      this._skipBreakController = createSkipBreakController(
        buildSkipBreakPageCapabilities(this, {})
      )
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
      this._activeSyncController = createActiveSyncController(
        buildActiveSyncPageCapabilities(this, { api })
      )
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
    return this._activeSessionReconciler().fetchActive()
  },

  _activeSessionReconciler() {
    if (!this._activeSessionReconcile) {
      this._activeSessionReconcile = createPomodoroActiveSessionReconciler(
        buildPomodoroActiveSessionReconcilerPageCapabilities(this, { api })
      )
    }
    return this._activeSessionReconcile
  },

  _restoreSession(session) {
    if (session.preset === 'free') {
      return this._restoreFreeSession(session)
    }
    if (!this._countdownSessionRestoreController) {
      this._countdownSessionRestoreController = createCountdownSessionRestoreController(
        buildCountdownSessionRestorePageCapabilities(this, { api })
      )
    }
    return this._countdownSessionRestoreController.restore(session)
  },

  _restoreFreeSession(session) {
    if (!this._freeSessionRestoreController) {
      this._freeSessionRestoreController = createFreeSessionRestoreController(
        buildFreeSessionRestorePageCapabilities(this, { api })
      )
    }
    return this._freeSessionRestoreController.restore(session)
  },

  _restoreBreak() {
    return this._getBreakRestoreController().restore()
  },

  _getBreakRestoreController() {
    if (!this._breakRestoreController) {
      this._breakRestoreController = createBreakRestoreController(
        buildBreakRestorePageCapabilities(this, { api })
      )
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
      this._canvasInitController = createCanvasInitController(
        buildCanvasInitPageCapabilities(this, {})
      )
    }
    return this._canvasInitController
  },

  _buildRingCache(isBreak) {
    return buildRingCache(this._ctx, this._canvasSize, isBreak, this.data.isFreeTimer)
  },

  _getDrawRingController() {
    if (!this._drawRingController) {
      this._drawRingController = createDrawRingController(
        buildDrawRingPageCapabilities(this, { api })
      )
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
      this._statsController = createStatsController(
        buildStatsPageCapabilities(this, { api })
      )
    }
    return this._statsController
  },

  async loadTodayStats() {
    return this._getStatsController().load()
  },

  goStats() {
    this._navigatingToStats = true
    wx.navigateTo({ url: `/subpackages/productivity/pomodoro-stats/index${this.data.guestMode ? '?guest=1' : ''}` })
  },

  /* ==================== Theme ==================== */

  _getThemeController() {
    if (!this._themeController) {
      this._themeController = createThemeController(
        buildThemePageCapabilities(this, {})
      )
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
      this._fontSizeController = createFontSizeController(
        buildFontSizePageCapabilities(this, {})
      )
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
      this._subjectViewController = createSubjectViewController(
        buildSubjectViewPageCapabilities(this, {})
      )
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
      this._presetViewController = createPresetViewController(
        buildPresetViewPageCapabilities(this, {})
      )
    }
    return this._presetViewController
  },

  _nextCelebrationType() {
    return this._getCelebrationTypeController().next()
  },

  _getCelebrationTypeController() {
    if (!this._celebrationTypeController) {
      this._celebrationTypeController = createCelebrationTypeController(
        buildCelebrationTypePageCapabilities(this, {})
      )
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
      this._dateExamController = createDateExamController(
        buildDateExamPageCapabilities(this, { api })
      )
    }
    return this._dateExamController
  },

})

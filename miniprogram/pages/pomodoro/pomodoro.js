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
const { buildSubjectChoices, normalizeCachedSubjects, subjectIconByCode } = require('./utils/subject-options')
const { createCountdownController } = require('./utils/countdown-controller')
const { createFreeTimerController } = require('./utils/free-timer-controller')
const { buildRingCache, shouldDrawRing } = require('./utils/ring-geometry')
const conflictState = require('./utils/terminal-conflict-state')
const {
  CANVAS_INIT_MAX_RETRIES,
  canvasRetryDelay,
  evaluateCanvasLayout,
  buildCanvasSetup,
} = require('./utils/canvas-layout')
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
const { buildCancelEndConfirmPlan } = require('./utils/cancel-confirm-state')
const {
  findRouteSubject,
  findLegacySubject,
  findSubjectById,
} = require('./utils/subject-selection')
const { formatElapsedSec, formatCountdownDisplay, calculateElapsedMs } = require('./utils/timer-math')
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
  _pauseToggleLocked: false,
  _pauseToggleUnlockTimer: null,
  _syncRetryController: null,
  _statsRequestSeq: 0,

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
    this._statsRequestSeq = (this._statsRequestSeq || 0) + 1
    this._unregisterNetworkStatusListener()
    if (this._themeSwitchTimer) {
      clearTimeout(this._themeSwitchTimer)
      this._themeSwitchTimer = null
    }
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
    if (this._pauseToggleUnlockTimer) {
      clearTimeout(this._pauseToggleUnlockTimer)
      this._pauseToggleUnlockTimer = null
    }
    this._pauseToggleLocked = false
  },

  _acquirePauseToggleLock() {
    if (this._pauseToggleLocked) return false
    this._pauseToggleLocked = true
    this._pauseToggleUnlockTimer = setTimeout(() => {
      this._pauseToggleUnlockTimer = null
      this._pauseToggleLocked = false
    }, POMODORO_PAUSE_TOGGLE_COOLDOWN_MS)
    return true
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
    // Resolve presentation from current assets, not the cached icon paths.
    const { choices, aggregate, leaves, coreSubjects } = normalizeCachedSubjects(flat)
    this.setData({
      subjects: choices,
      aggregateAvailable: !!aggregate && coreSubjects.length === 4,
      coreSubjects,
      subjectsLoading: false,
      subjectsError: '',
    })
    // 旧版 pomodoro_running_state 缓存可能只带 subject_code，用已加载列表迁移到 subject_id
    this._migrateRunningStateCache(leaves)

    // Route presets can target either a stable subject_id or the canonical 408 subject_code.
    // subject_code keeps strategy-driven Next Best Action usable before a subject has practice data.
    const route = { subjectId: this.data.fromSubjectId, subjectCode: this.data.fromSubjectCode }
    const routeSelection = (route.subjectId || route.subjectCode)
      ? findRouteSubject({ route, aggregate, leaves, coreSubjects }) : null
    if (routeSelection) {
      this.setData(routeSelection)
      this._updateComputedFields()
    }
    // 恢复的旧会话可能只有 subject_code（无 subject_id），用已加载列表回填
    const legacySelection = findLegacySubject(this.data.selectedSubject, leaves)
    if (legacySelection) {
      this.setData(legacySelection)
      this._updateComputedFields()
    }
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

  _buildUnknownStartAttempt(overrides = {}) {
    return buildUnknownStartAttempt(this.data, overrides, api.createClientStartId, api.now())
  },

  _unknownStartPayload(attempt) {
    return buildUnknownStartPayload(attempt)
  },

  _matchesUnknownStartAttempt(session, attempt) {
    return matchesUnknownStartAttempt(session, attempt)
  },

  _startCancellationAt(session, cancelAt) {
    const requestedAt = Number(cancelAt)
    const fallback = Number.isFinite(requestedAt) && requestedAt > 0 ? requestedAt : api.now()
    const serverStartAt = session && session.start_time ? parseServerTime(session.start_time) : NaN
    return Number.isFinite(serverStartAt) ? Math.max(serverStartAt, fallback) : fallback
  },

  async _reconcileUnknownStartAttempt(explicitAttempt) {
    let attempt = explicitAttempt
    const stored = this._safeGetPomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'unknown start')
    if (!stored.ok) return 'storage_error'

    // onHide may mark the persisted attempt cancelIfFound while the original
    // request is still unwinding. Prefer that latest copy even when the caller
    // passes its older in-memory attempt object.
    const storedAttempt = stored.value
    if (storedAttempt && (!attempt || storedAttempt.clientStartId === attempt.clientStartId)) {
      attempt = storedAttempt
    }

    if (!attempt || !attempt.clientStartId) {
      if (attempt && !this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'invalid unknown start')) {
        return 'storage_error'
      }
      return 'none'
    }

    const payload = this._unknownStartPayload(attempt)
    if (!payload) {
      return this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'invalid unknown start payload')
        ? 'none'
        : 'storage_error'
    }

    let session
    try {
      // Retry the exact same idempotent /start instead of guessing from /active.
      // If the first request committed, the backend returns that same row. If it
      // did not commit and another device owns the active row, this gets a 409 and
      // never mistakes/interrupts the other device's timer.
      session = await api.post('/pomodoro/start', payload)
    } catch (e) {
      const statusCode = Number(e && e.statusCode) || 0
      if (statusCode === 0 || statusCode >= 500) return 'offline'
      return this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'settled failed start')
        ? 'none'
        : 'storage_error'
    }

    if (!this._matchesUnknownStartAttempt(session, attempt)) {
      return this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'mismatched unknown start')
        ? 'none'
        : 'storage_error'
    }

    pomodoroTaskTypes.recordSession(session, attempt.taskType || this.data.selectedTaskType)

    if (attempt.cancelIfFound && (session.status === 'running' || session.status === 'paused')) {
      const cancelAt = this._startCancellationAt(session, attempt.cancelAt)
      const pending = this._setPendingPomodoroSync('interrupt', session.id, cancelAt)
      if (!pending) {
        // Keep/reinforce the idempotent start marker so a later storage recovery
        // can still find and cancel the server row. Never clear the only recovery
        // credential when the interrupt intent itself was not durable.
        this._safeSetPomodoroStorage(POMODORO_UNKNOWN_START_KEY, {
          ...attempt,
          cancelIfFound: true,
          cancelAt,
        }, 'retain cancelled unknown start')
        return 'storage_error'
      }
      this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'interrupt queued for unknown start')
      await this._retryPendingPomodoroSync()
      this._resetToIdle()
      return 'cancelled'
    }

    if (session.status === 'running' || session.status === 'paused') {
      // Do not restore a timer while its unknown-start marker is still durable.
      // If cleanup fails, a later onHide could otherwise mark the stale marker as
      // cancelIfFound and unexpectedly interrupt a legitimate running session.
      if (!this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'resolved active start')) {
        return 'storage_error'
      }
      if (this._pageVisible && this._restoreSession(session) === false) return 'storage_error'
      return 'restored'
    }

    return this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'resolved terminal start')
      ? 'settled'
      : 'storage_error'
  },

  async _postPomodoroStartWithReconciliation(payload, startSeq) {
    const clientStartId = payload.client_start_id || api.createClientStartId()
    const requestPayload = { ...payload, client_start_id: clientStartId }
    const attempt = this._buildUnknownStartAttempt({
      clientStartId,
      subjectId: requestPayload.subject_id,
      chapterId: requestPayload.chapter_id || null,
      preset: requestPayload.preset,
      workDuration: requestPayload.work_duration,
      breakDuration: requestPayload.break_duration,
      notificationEnabled: !!requestPayload.notification_enabled,
    })

    // The idempotency key is useful only if it survives a lost response. Refuse
    // to send /start unless the recovery credential is durable first.
    if (!this._safeSetPomodoroStorage(POMODORO_UNKNOWN_START_KEY, attempt, 'before pomodoro start')) {
      this._showPomodoroPersistenceError()
      this._resetToIdle()
      return { handled: true, session: null }
    }

    let session
    try {
      session = await api.post('/pomodoro/start', requestPayload)
    } catch (e) {
      const statusCode = Number(e && e.statusCode) || 0
      const resultIsUncertain = statusCode === 0 || statusCode >= 500
      if (resultIsUncertain) {
        const resolution = await this._reconcileUnknownStartAttempt(attempt)
        if (resolution === 'cancelled' || resolution === 'restored') {
          return { handled: true, session: null }
        }
        if (resolution === 'settled') {
          this._resetToIdle()
          return { handled: true, session: null }
        }
        if (resolution === 'storage_error') {
          this._showPomodoroPersistenceError()
          this._resetToIdle()
          return { handled: true, session: null }
        }
      } else if (!this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'failed pomodoro start')) {
        this._showPomodoroPersistenceError()
        this._resetToIdle()
        return { handled: true, session: null }
      }
      throw e
    }

    const latestStored = this._safeGetPomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'completed pomodoro start')
    const latestAttempt = latestStored.ok && latestStored.value ? latestStored.value : attempt

    if (!this._pageVisible || startSeq !== this._startRequestSeq) {
      const cancelAt = this._startCancellationAt(session, latestAttempt.cancelAt)
      const pending = this._setPendingPomodoroSync('interrupt', session.id, cancelAt)
      if (pending) {
        // Once the interrupt intent is durable, pending sync becomes the recovery
        // source of truth and the start marker may be removed best-effort.
        this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'start cancelled after response')
        this._retryPendingPomodoroSync()
      } else {
        // If pending storage is unavailable, preserve the original idempotent key
        // and mark it for cancellation. A later onShow can safely replay /start and
        // enqueue the interrupt without guessing which active row belongs to us.
        this._safeSetPomodoroStorage(POMODORO_UNKNOWN_START_KEY, {
          ...latestAttempt,
          cancelIfFound: true,
          cancelAt,
        }, 'retain cancelled start after response')
      }
      return { handled: true, session: null }
    }

    if (!latestStored.ok || !this._safeRemovePomodoroStorage(POMODORO_UNKNOWN_START_KEY, 'accepted pomodoro start')) {
      this._showPomodoroPersistenceError()
      this._resetToIdle()
      return { handled: true, session: null }
    }
    return { handled: false, session }
  },

  /* ==================== Start Ceremony ==================== */

  async startSession() {
    // A real in-flight lock is separate from lifecycle generations. A rapid
    // double tap must not invalidate the first successful /start response and
    // then enqueue an interrupt for the very session the UI is about to restore.
    if (this._startInFlight || this.data.phase === PHASE.CEREMONY || this.data.phase === PHASE.RUNNING) return
    this._startInFlight = true

    const startSeq = (this._startRequestSeq || 0) + 1
    this._startRequestSeq = startSeq

    try {
      // Never overwrite an unresolved idempotent start with a new client key.
      // Replaying the previous key either restores that exact session or proves
      // deterministically that no such start exists.
      const unresolvedStart = await this._reconcileUnknownStartAttempt()
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      if (unresolvedStart === 'offline') {
        wx.showToast({ title: '上次启动结果待确认，请联网后重试', icon: 'none' })
        return
      }
      if (unresolvedStart === 'storage_error') {
        this._showPomodoroPersistenceError()
        return
      }
      if (unresolvedStart === 'restored' || unresolvedStart === 'cancelled') return

      // Flush any earlier local actions first. A terminal complete/interrupt that is
      // still pending would otherwise make /start collide with the old active row.
      const pendingQueue = this._getPendingPomodoroSyncQueue()
      if (pendingQueue === null) {
        this._showPomodoroPersistenceError()
        return
      }
      if (pendingQueue.length) {
        const synced = await this._retryPendingPomodoroSync()
        if (!this._pageVisible || startSeq !== this._startRequestSeq) return
        if (!synced) {
          wx.showToast({ title: '上次专注尚未同步，请联网后重试', icon: 'none' })
          return
        }
      }

      if (!this.data.selectedSubjectId || !this.data.selectedSubject) {
        wx.showToast({ title: '请选择学习科目', icon: 'none' })
        return
      }
      if (this.data.subjectsError) {
        wx.showToast({ title: '科目加载异常，请重试', icon: 'none' })
        return
      }

      if (this.data.selectedPreset === 'free') {
        await this._startFreeSession(startSeq)
        return
      }

      this.setData({ phase: PHASE.CEREMONY })
      await new Promise(r => setTimeout(r, this.data.selectedPreset === 'debug' ? 1000 : 2500))
      if (!this._pageVisible || startSeq !== this._startRequestSeq || this.data.phase !== PHASE.CEREMONY) return

      const startResult = await this._postPomodoroStartWithReconciliation({
        subject_id: this.data.selectedSubjectId,
        allocation_mode: this.data.allocationMode,
        chapter_id: this.data.fromChapterId || null,
        preset: this.data.selectedPreset,
        work_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.workDuration,
        break_duration: this.data.selectedPreset === 'debug' ? 1 : this.data.breakDuration,
      }, startSeq)
      if (startResult.handled || !startResult.session) return
      pomodoroTaskTypes.recordSession(startResult.session, this.data.selectedTaskType)
      this._beginCountdown(startResult.session)
    } catch (e) {
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      const detail = (e && (e.detail || e.message || '')) || ''
      const isActiveConflict = (e && e.statusCode === 409) || /active|running|进行中/.test(detail)
      if (isActiveConflict) {
        wx.showToast({ title: '已有进行中的专注，请先结束', icon: 'none' })
        const active = await this._fetchActiveSession()
        if (this._pageVisible && startSeq === this._startRequestSeq && this._isPomodoroStorageError(active)) {
          this._showPomodoroPersistenceError()
          this.setData({ phase: PHASE.IDLE })
        } else if (this._pageVisible && startSeq === this._startRequestSeq && active) {
          if (this._restoreSession(active) === false) this.setData({ phase: PHASE.IDLE })
        } else if (this._pageVisible && startSeq === this._startRequestSeq) {
          this.setData({ phase: PHASE.IDLE })
        }
      } else {
        wx.showToast({ title: '启动失败', icon: 'none' })
        this.setData({ phase: PHASE.IDLE })
      }
    } finally {
      this._startInFlight = false
    }
  },

  /* ==================== Free Timer ==================== */

  async _startFreeSession(existingStartSeq) {
    const startSeq = existingStartSeq || ((this._startRequestSeq || 0) + 1)
    if (!existingStartSeq) this._startRequestSeq = startSeq

    const pendingQueue = this._getPendingPomodoroSyncQueue()
    if (pendingQueue === null) {
      this._showPomodoroPersistenceError()
      return
    }
    if (pendingQueue.length) {
      const synced = await this._retryPendingPomodoroSync()
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      if (!synced) {
        wx.showToast({ title: '上次专注尚未同步，请联网后重试', icon: 'none' })
        return
      }
    }
    try {
      const startResult = await this._postPomodoroStartWithReconciliation({
        subject_id: this.data.selectedSubjectId,
        allocation_mode: this.data.allocationMode,
        chapter_id: this.data.fromChapterId || null,
        preset: 'free',
        work_duration: 0,
        break_duration: 0,
      }, startSeq)
      if (startResult.handled || !startResult.session) return
      pomodoroTaskTypes.recordSession(startResult.session, this.data.selectedTaskType)
      this._beginFreeTimer(startResult.session)
    } catch (e) {
      if (!this._pageVisible || startSeq !== this._startRequestSeq) return
      const detail = (e && (e.detail || e.message || '')) || ''
      const isActiveConflict = (e && e.statusCode === 409) || /active|running|进行中/.test(detail)
      if (isActiveConflict) {
        wx.showToast({ title: '已有进行中的专注，请先结束', icon: 'none' })
        const active = await this._fetchActiveSession()
        if (this._pageVisible && startSeq === this._startRequestSeq && this._isPomodoroStorageError(active)) {
          this._showPomodoroPersistenceError()
        } else if (this._pageVisible && startSeq === this._startRequestSeq && active) {
          this._restoreSession(active)
        }
      } else {
        wx.showToast({ title: '启动失败，请重试', icon: 'none' })
      }
    }
  },

  _beginFreeTimer(session) {
    const startTime = parseServerTime(session.start_time)
    const totalPausedMs = Math.max(0, Number(session.total_paused_sec || 0) * 1000)
    const now = api.now()
    const elapsedMs = Math.max(0, now - startTime - totalPausedMs)
    const elapsedSec = Math.min(Math.floor(elapsedMs / 1000), Math.floor(FREE_TIMER_MAX_MS / 1000))
    const fmt = formatElapsedSec(elapsedSec)

    this._clearTimer()
    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.totalPausedMs = totalPausedMs
    // Server start_time is the single clock origin. Do not hide /start network
    // latency behind a client-only display offset, otherwise UI and statistics
    // diverge by the request round-trip time.
    this._timerState.freeDisplayOffsetMs = 0
    this._timerState.pauseStartTime = null
    this._timerState.elapsedSec = elapsedSec
    this._timerState.freeFriendlyText = fmt.friendly
    this._timerState.progress = 1
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isFreeTimer: true,
      isPaused: false,
      freeDisplayTime: fmt.display,
      showEndConfirm: false,
    })
    this._updateComputedFields()
    if (elapsedMs >= FREE_TIMER_MAX_MS) {
      this._autoFinishFreeTimer()
      return
    }
    this._startFreeTimerInterval()
    wx.nextTick(() => {
      this._initCanvas(true)
      this.drawRing(0, false)
    })
  },

  _updateFreeElapsed() {
    if (!this.data.isFreeTimer) return
    if (this.data.showEndConfirm) return

    if (this.data.isPaused) {
      const fmt = formatElapsedSec(this._timerState.elapsedSec || 0)
      this.setData({
        freeDisplayTime: fmt.display,
      })
      this._timerState.freeFriendlyText = fmt.friendly
      return
    }

    const elapsedMs = this._getEffectiveFreeElapsedMs()
    // Cap display at 5-hour max so UI never shows >05:00:00
    const cappedMs = Math.min(elapsedMs, FREE_TIMER_MAX_MS)
    const elapsedSec = Math.floor(cappedMs / 1000)

    if (elapsedSec === this._timerState.elapsedSec) return
    const fmt = formatElapsedSec(elapsedSec)
    this._timerState.elapsedSec = elapsedSec
    this._timerState.freeFriendlyText = fmt.friendly
    this.setData({
      freeDisplayTime: fmt.display,
    })
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
    if (!this._timerState.sessionId || this.data.actionLoading) return
    const sessionId = this._timerState.sessionId
    const pauseStartedAt = api.now()

    const pending = this._setPendingPomodoroSync('pause', sessionId, pauseStartedAt)
    if (!pending) {
      this._showPomodoroPersistenceError()
      return
    }

    this._updateFreeElapsed()
    this._clearFreeTimerInterval()
    this._timerState.pauseStartTime = pauseStartedAt
    this._timerState.freeFriendlyText = formatElapsedSec(this._timerState.elapsedSec).friendly
    this.setData({ isPaused: true, actionLoading: true })
    this._safeSetPomodoroStorage('pomodoro_free_pause', {
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: pauseStartedAt,
      sessionId,
      elapsedSec: this._timerState.elapsedSec,
      freeDisplayOffsetMs: 0,
    }, 'free pause snapshot')

    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已暂停，网络恢复后自动同步', icon: 'none' })
    })
  },

  async _resumeFreeTimer() {
    if (!this._timerState.sessionId || this.data.actionLoading) return
    const sessionId = this._timerState.sessionId
    const now = api.now()
    const openPauseMs = this._timerState.pauseStartTime
      ? Math.max(0, now - this._timerState.pauseStartTime)
      : 0
    const localTotalPausedMs = Math.max(0, Number(this._timerState.totalPausedMs || 0) + openPauseMs)

    // Queue ordering is important: if a previous /pause timed out, it stays ahead
    // of this /resume and is synchronized first instead of being overwritten.
    // Persist the intent before changing local UI so a storage failure cannot turn
    // a durable paused state into an unrecoverable local-only resume.
    const pending = this._setPendingPomodoroSync('resume', sessionId, now)
    if (!pending) {
      this._showPomodoroPersistenceError()
      return
    }

    this._safeSetPomodoroStorage('pomodoro_pause_adjustment', {
      sessionId,
      totalPausedMs: localTotalPausedMs,
      savedAt: now,
    }, 'free resume adjustment')
    this._safeRemovePomodoroStorage('pomodoro_free_pause', 'free resume snapshot')
    this._timerState.totalPausedMs = localTotalPausedMs
    this._timerState.pauseStartTime = null
    this.setData({ isPaused: false, ringCanvasVisible: true, actionLoading: true })
    this._startFreeTimerInterval()

    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已继续计时，网络恢复后自动同步', icon: 'none' })
    })
  },

  async _reconcileAfterResumeError(e, sessionId) {
    if (!e || e.code !== 404) {
      wx.showToast({ title: '继续失败，请重试', icon: 'none' })
      return
    }
    try {
      const active = await api.get('/pomodoro/active')
      if (!active || active.id !== sessionId) {
        this._resetToIdle()
        wx.showToast({ title: '当前专注已结束或失效', icon: 'none' })
        return
      }
      if (active.status !== 'running') {
        wx.showToast({ title: '继续失败，请稍后重试', icon: 'none' })
        return
      }
      // Server says running — fix local state and continue
      const startTime = parseServerTime(active.start_time)
      const totalPausedSec = active.total_paused_sec || 0
      const totalPausedMs = totalPausedSec * 1000
      if (this.data.isFreeTimer) {
        this._timerState.sessionStartTime = startTime
        this._timerState.totalPausedMs = this._mergeLocalPauseAdjustment(active.id, totalPausedMs)
        this._timerState.pauseStartTime = null

        const elapsedMs = this._getEffectiveFreeElapsedMs()
        const elapsed = Math.floor(elapsedMs / 1000)
        const fmt = formatElapsedSec(elapsed)
        this._timerState.elapsedSec = elapsed
        this.setData({
          isPaused: false,
          freeDisplayTime: fmt.display,
          ringCanvasVisible: true,
        })
        this._startFreeTimerInterval()
        this._safeRemovePomodoroStorage('pomodoro_free_pause', 'best-effort cleanup')
      } else {
        const now = api.now()
        const totalSec = this._getCurrentTotalSec()

        // Merge with local pause adjustment
        const effectiveTotalPausedMs = this._mergeLocalPauseAdjustment(active.id, totalPausedMs)

        const elapsed = Math.floor((now - startTime - effectiveTotalPausedMs) / 1000)
        const remainingSec = Math.max(0, totalSec - elapsed)
        this._timerState.sessionStartTime = startTime
        this._timerState.totalPausedMs = effectiveTotalPausedMs
        this._timerState.pauseStartTime = null
        this._timerState.remainingSec = remainingSec
        this._timerState.progress = totalSec > 0 ? remainingSec / totalSec : 0
        this.setData({
          isPaused: false,
          remainingSec,
          displayMin: String(Math.floor(remainingSec / 60)).padStart(2, '0'),
          displaySec: String(remainingSec % 60).padStart(2, '0'),
          ringCanvasVisible: true,
        })
        this._startTimer(totalSec)
        this._safeRemovePomodoroStorage('pomodoro_pause', 'best-effort cleanup')
      }
      wx.showToast({ title: '已恢复计时', icon: 'none' })
    } catch (_) {
      wx.showToast({ title: '继续失败，请重试', icon: 'none' })
    }
  },

  _isValidConfirmSnapshot(snapshot) {
    if (!snapshot || !snapshot.sessionId) return false
    if (!snapshot.mode) return false
    if (snapshot.confirmVisible === false) return false
    if (!snapshot.openedAt) return false
    // Snapshots older than 1 hour are stale
    if (api.now() - snapshot.openedAt > 3600000) return false
    return true
  },

  async _showEndFreeConfirm() {
    if (!this._timerState.sessionId || this.data.actionLoading) return

    const now = api.now()
    const wasPaused = !!this.data.isPaused
    const elapsed = Math.max(0, this._timerState.elapsedSec || 0)
    const fmt = formatElapsedSec(elapsed)

    const confirmActionSeq = (this._confirmActionSeq || 0) + 1
    this._confirmActionSeq = confirmActionSeq
    const snapshot = {
      mode: 'free-complete',
      confirmActionSeq,
      sessionId: this._timerState.sessionId,
      openedAt: now,
      wasPaused,
      pausedByConfirm: !wasPaused,
      elapsedSec: elapsed,
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: this._timerState.pauseStartTime || null,
      sessionStartTime: this._timerState.sessionStartTime,
      backendPauseDone: false,
      confirmVisible: true,
      freeDisplayOffsetMs: 0,
    }

    if (!this._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'free confirm snapshot')) {
      this._showPomodoroPersistenceError()
      return
    }
    if (!wasPaused && !this._setPendingPomodoroSync('pause', this._timerState.sessionId, now)) {
      this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'free confirm rollback')
      this._showPomodoroPersistenceError()
      return
    }

    this._confirmTimerSnapshot = snapshot
    this._clearFreeTimerInterval()
    this._timerState.elapsedSec = elapsed
    this._timerState.pauseStartTime = now
    this._timerState.freeFriendlyText = fmt.friendly
    this._timerState.endConfirmMode = 'free-complete'
    this.setData({
      ...buildEndConfirmViewModel('free-complete', snapshot),
      ringCanvasVisible: true,
      freeDisplayTime: fmt.display,
      isPaused: true,
    })

    // Backend pause async — don't block UI
    if (!wasPaused) {
      this._postPauseWithRetry(this._timerState.sessionId, snapshot.openedAt)
        .then(() => {
          if (snapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
          snapshot.backendPauseDone = true
          this._confirmTimerSnapshot = snapshot
          this._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'confirm snapshot refresh')
        })
        .catch(e => console.warn('free confirm pause backend sync failed', e))
    }
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
    const pending = this._setPendingPomodoroSync('pause', sessionId, clientActionAt)
    if (!pending) throw new Error('pomodoro local persistence unavailable')
    const synced = await this._retryPendingPomodoroSync()
    if (!synced) throw new Error('pomodoro pause sync pending')
    return true
  },

  async _pauseCountdownForEndConfirm() {
    if (!this._timerState.sessionId || this.data.actionLoading) return false

    const now = api.now()
    const totalSec = this._getCurrentTotalSec()
    const totalMs = Math.max(1, totalSec * 1000)

    const remainingMs = this._countdownEndAt
      ? Math.max(0, this._countdownEndAt - now)
      : Math.max(0, (this._timerState.remainingSec || 0) * 1000)

    const remainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
    const progress = totalMs > 0 ? remainingMs / totalMs : 0
    const wasPaused = !!this.data.isPaused

    const confirmActionSeq = (this._confirmActionSeq || 0) + 1
    this._confirmActionSeq = confirmActionSeq
    const snapshot = {
      mode: 'countdown-interrupt',
      confirmActionSeq,
      sessionId: this._timerState.sessionId,
      openedAt: now,
      wasPaused: wasPaused,
      pausedByConfirm: !wasPaused,
      phase: this.data.phase,
      totalSec: totalSec,
      totalMs: totalMs,
      remainingMs: remainingMs,
      remainingSec: remainingSec,
      progress: progress,
      sessionStartTime: this._timerState.sessionStartTime,
      countdownEndAt: this._countdownEndAt,
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: this._timerState.pauseStartTime || null,
      backendPauseDone: false,
      confirmVisible: true,
    }

    // The confirm snapshot and, when needed, the backend pause intent are both
    // durable before the local timer is stopped. This keeps the operation
    // fail-closed when local storage is unavailable.
    if (!this._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'countdown confirm snapshot')) {
      this._showPomodoroPersistenceError()
      return false
    }
    if (!wasPaused && !this._setPendingPomodoroSync('pause', this._timerState.sessionId, now)) {
      this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'countdown confirm rollback')
      this._showPomodoroPersistenceError()
      return false
    }

    this._confirmTimerSnapshot = snapshot
    this._clearTimer()
    this._countdownEndAt = 0

    const fmt = this._formatCountdownDisplay(remainingSec)

    this._timerState.pauseStartTime = now
    this._timerState.remainingSec = remainingSec
    this._timerState.progress = progress
    this.setData({
      isPaused: true,
      displayMin: fmt.min,
      displaySec: fmt.sec,
    })

    this.drawRing(totalSec, this.data.phase === 'break')

    this._timerState.endConfirmMode = 'countdown-interrupt'

    // Sync backend pause asynchronously; the dialog appears immediately. The
    // confirmActionSeq guard prevents a late response from mutating a cancelled
    // confirmation snapshot.
    if (!wasPaused) {
      this._postPauseWithRetry(this._timerState.sessionId, snapshot.openedAt)
        .then(() => {
          if (snapshot.confirmActionSeq !== this._confirmActionSeq || !this.data.showEndConfirm) return
          snapshot.backendPauseDone = true
          this._confirmTimerSnapshot = snapshot
          this._safeSetPomodoroStorage('pomodoro_confirm_pause', snapshot, 'confirm snapshot refresh')
        })
        .catch(e => console.warn('confirm pause backend sync failed', e))
    }

    return true
  },

  async _showCountdownInterruptConfirm() {
    if (this.data.actionLoading) return

    const ok = await this._pauseCountdownForEndConfirm()
    if (!ok || !this._confirmTimerSnapshot) return

    const snapshot = this._confirmTimerSnapshot

    this.setData({
      ...buildEndConfirmViewModel('countdown-interrupt', snapshot),
      ringCanvasVisible: true,
    })

    wx.nextTick(() => {
      this._initCanvas(true)
      this.drawRing(snapshot.totalSec, snapshot.phase === 'break')
    })
  },

  async cancelEndConfirm() {
    if (this.data.actionLoading) return

    const mode = this._timerState.endConfirmMode
    let snapshot = this._confirmTimerSnapshot
    if (!snapshot) {
      const storedConfirm = this._safeGetPomodoroStorage('pomodoro_confirm_pause', 'cancel end confirm')
      if (!storedConfirm.ok) {
        this._showPomodoroPersistenceError()
        return
      }
      snapshot = storedConfirm.value
    }
    const now = api.now()
    this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
    const plan = buildCancelEndConfirmPlan({
      mode,
      snapshot,
      now,
      freeNow: mode === 'free-complete' ? api.now() : now,
      isPaused: this.data.isPaused,
    })
    if (plan.snapshot) this._confirmTimerSnapshot = plan.snapshot
    Object.assign(this._timerState, plan.timer)
    if (plan.adjustment) {
      if (!this._setPendingPomodoroSync('resume', plan.adjustment.sessionId, now)) {
        this._showPomodoroPersistenceError()
        return
      }
      this._safeSetPomodoroStorage('pomodoro_pause_adjustment', plan.adjustment, 'cancel confirm resume adjustment')
    }

    this.setData(plan.view)
    if (plan.removeConfirmStorage) {
      this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'best-effort cleanup')
    }
    if (plan.clearSnapshot) this._confirmTimerSnapshot = null
    if (plan.startTimer) {
      this._countdownTotalSec = plan.startTimer.totalSec
      this._startTimer(plan.startTimer.totalSec, {
        remainingMs: plan.startTimer.remainingMs,
        forceRunning: true,
      })
    }
    if (plan.startFreeTimer) this._startFreeTimerInterval()
    if (plan.restartFreeTimer) this._restartFreeTimerInterval()
    if (plan.redraw) {
      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(plan.redraw.totalSec, plan.redraw.phase === 'break')
      })
    }
    if (plan.redrawFree) this._redrawFreeRingAfterOverlay()
    if (plan.retryPending) {
      this._retryPendingPomodoroSync().then(synced => {
        if (!synced) console.warn('resume after cancel confirm pending; keep local timer')
      })
    }
  },

  async confirmEndTimer() {
    if (this.data.actionLoading) return

    const mode = this._timerState.endConfirmMode
    const snapshot = this._confirmTimerSnapshot

    if (mode === 'free-complete') {
      return this._confirmEndFreeTimer()
    }

    if (mode === 'countdown-interrupt') {
      return this._confirmInterruptCountdown()
    }

    console.warn('[pomodoro] invalid end confirm mode', {
      mode,
      sessionId: this._timerState.sessionId,
      snapshotMode: snapshot && snapshot.mode,
    })
    wx.showToast({
      title: '结束状态异常，请重新操作',
      icon: 'none',
    })
  },

  async _confirmEndFreeTimer() {
    if (this.data.actionLoading) return
    const sessionId = this._timerState.sessionId
    if (!sessionId) {
      this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
      this._confirmTimerSnapshot = null
      this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'best-effort cleanup')
      this.setData({ showEndConfirm: false, actionLoading: false })
      return
    }
    this._confirmActionSeq = (this._confirmActionSeq || 0) + 1
    this.setData({ showEndConfirm: false, actionLoading: false })
    this._clearFreeTimerInterval()
    this._completeFreeTimerSession()
  },

  async _confirmInterruptCountdown() {
    if (!this._timerState.sessionId || this.data.actionLoading) return

    const sessionId = this._timerState.sessionId
    const snapshot = this._confirmTimerSnapshot
    let totalPausedMs = this._timerState.totalPausedMs || 0
    if (snapshot && snapshot.openedAt) {
      totalPausedMs = Math.max(0, Number(snapshot.totalPausedMs || 0) + (api.now() - snapshot.openedAt))
    }
    this._timerState.totalPausedMs = totalPausedMs
    this._confirmActionSeq = (this._confirmActionSeq || 0) + 1

    // Persist the terminal intent before ending locally. Terminal actions have
    // reserved queue capacity, so reaching the pause/resume safety valve still
    // allows the user to finish the session.
    if (!this._setPendingPomodoroSync('interrupt', sessionId, api.now())) {
      this._showPomodoroPersistenceError()
      this.setData({ actionLoading: false })
      return
    }
    this._retryPendingPomodoroSync().then(synced => {
      const conflict = this._consumePomodoroTerminalConflict(sessionId, 'interrupt')
      if (conflict) {
        this._handlePomodoroTerminalConflict(sessionId, conflict)
        return
      }
      if (!synced) wx.showToast({ title: '网络恢复后将自动同步', icon: 'none' })
      else this.loadTodayStats()
    })

    wx.showToast({ title: '已结束本次专注', icon: 'none' })
    this._safeRemovePomodoroStorage('pomodoro_pause_adjustment', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'best-effort cleanup')
    this._confirmTimerSnapshot = null
    this.setData({ showEndConfirm: false, actionLoading: false })
    this._resetToIdle()
  },

  async endSession() {
    if (!this._timerState.sessionId) return
    const sessionId = this._timerState.sessionId
    this._clearTimer()
    this._completePomodoroWithRetry(sessionId, api.now()).then(synced => {
      const conflict = this._consumePomodoroTerminalConflict(sessionId, 'complete')
      if (conflict) {
        this._handlePomodoroTerminalConflict(sessionId, conflict)
        return
      }
      if (synced) this.loadTodayStats()
    })
    this._resetToIdle()
  },

  async interruptSession() {
    if (!this._timerState.sessionId) return

    if (this.data.isFreeTimer) {
      this._showEndFreeConfirm()
      return
    }

    this._showCountdownInterruptConfirm()
  },

  /* ==================== Countdown Timer ==================== */

  _beginCountdown(session) {
    const startTime = parseServerTime(session.start_time)
    const totalSec = this.data.selectedPreset === 'debug' ? 10 : this.data.workDuration * 60
    const totalPausedMs = Math.max(0, Number(session.total_paused_sec || 0) * 1000)
    const elapsedMs = Math.max(0, api.now() - startTime - totalPausedMs)
    const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)

    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.remainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
    this._timerState.progress = totalSec > 0 ? remainingMs / (totalSec * 1000) : 0
    this._timerState.totalPausedMs = totalPausedMs
    this._timerState.pauseStartTime = null
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isPaused: false,
    })
    this._updateComputedFields()

    // Use the server-issued start_time as the only clock origin. If /start took
    // two seconds to return, the first frame correctly begins near 24:58 instead
    // of showing a client-only 25:00 that disagrees with persisted statistics.
    if (remainingMs <= 0) {
      this._onWorkComplete()
      return
    }
    this._startTimer(totalSec, { remainingMs, forceRunning: true })
  },

  togglePause() {
    if (
      this.data.phase !== PHASE.RUNNING ||
      !this._timerState.sessionId ||
      this.data.actionLoading ||
      this.data.showEndConfirm ||
      !this._acquirePauseToggleLock()
    ) return

    if (this.data.isFreeTimer) {
      if (this.data.isPaused) {
        this._resumeFreeTimer()
      } else {
        this._pauseFreeTimer()
      }
    } else if (this.data.isPaused) {
      this._resumeSession()
    } else {
      this._pauseSession()
    }
  },

  async _pauseSession() {
    if (!this._timerState.sessionId || this.data.actionLoading) return
    const sessionId = this._timerState.sessionId
    const pauseStartedAt = api.now()

    const pending = this._setPendingPomodoroSync('pause', sessionId, pauseStartedAt)
    if (!pending) {
      this._showPomodoroPersistenceError()
      return
    }

    this._clearTimer()
    this._timerState.pauseStartTime = pauseStartedAt
    this.setData({ isPaused: true, actionLoading: true })
    this._safeSetPomodoroStorage('pomodoro_pause', {
      totalPausedMs: this._timerState.totalPausedMs || 0,
      pauseStartTime: pauseStartedAt,
      sessionId,
    }, 'countdown pause snapshot')

    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已暂停，网络恢复后自动同步', icon: 'none' })
    })
  },

  async _resumeSession() {
    if (typeof this._timerState.sessionStartTime !== 'number' || this._timerState.sessionStartTime <= 0) {
      console.warn('resume aborted: invalid sessionStartTime', this._timerState.sessionStartTime)
      this._resetToIdle()
      return
    }
    if (!this._timerState.sessionId || this.data.actionLoading) return

    const sessionId = this._timerState.sessionId
    const now = api.now()
    const openPauseMs = this._timerState.pauseStartTime
      ? Math.max(0, now - this._timerState.pauseStartTime)
      : 0
    const localTotalPausedMs = Math.max(0, Number(this._timerState.totalPausedMs || 0) + openPauseMs)
    const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60

    const pending = this._setPendingPomodoroSync('resume', sessionId, now)
    if (!pending) {
      this._showPomodoroPersistenceError()
      return
    }

    this._safeSetPomodoroStorage('pomodoro_pause_adjustment', {
      sessionId,
      totalPausedMs: localTotalPausedMs,
      savedAt: now,
    }, 'countdown resume adjustment')
    this._safeRemovePomodoroStorage('pomodoro_pause', 'countdown resume snapshot')
    this._timerState.totalPausedMs = localTotalPausedMs
    this._timerState.pauseStartTime = null
    this.setData({ isPaused: false, ringCanvasVisible: true, actionLoading: true })

    const elapsedMs = Math.max(0, now - this._timerState.sessionStartTime - localTotalPausedMs)
    const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)
    this._startTimer(totalSec, { remainingMs, forceRunning: true, reuseCanvas: true })

    this.setData({ actionLoading: false })
    this._retryPendingPomodoroSync().then(synced => {
      if (!synced) wx.showToast({ title: '已继续计时，网络恢复后自动同步', icon: 'none' })
    })
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

  _recordPomodoroTerminalConflict(sessionId, requestedAction, serverStatus) {
    const conflict = conflictState.createTerminalConflict(sessionId, requestedAction, serverStatus, api.now())
    // The conflict marker is the durable bridge between a server-side terminal
    // result and removal of the pending client mutation. Never acknowledge/drop
    // the pending action unless this marker has actually reached local storage.
    if (!this._safeSetPomodoroStorage(POMODORO_TERMINAL_CONFLICT_KEY, conflict, 'terminal conflict')) {
      return false
    }
    this._pomodoroTerminalConflict = conflict
    return true
  },

  _readPomodoroTerminalConflict() {
    if (this._pomodoroTerminalConflict) return this._pomodoroTerminalConflict
    const stored = this._safeGetPomodoroStorage(POMODORO_TERMINAL_CONFLICT_KEY, 'terminal conflict')
    if (!stored.ok) return { storageUnreadable: true }
    const conflict = stored.value
    if (conflictState.isValidTerminalConflict(conflict)) {
      this._pomodoroTerminalConflict = conflict
      return conflict
    }
    return null
  },

  // These helpers intentionally *peek* rather than durably deleting the marker.
  // The marker is acknowledged only after _handlePomodoroTerminalConflict has
  // successfully cleaned local state, so a process kill/storage error cannot
  // lose the only evidence of a cross-device terminal result.
  _consumePomodoroTerminalConflict(sessionId, requestedAction) {
    const conflict = this._readPomodoroTerminalConflict()
    if (this._isPomodoroStorageError(conflict)) return conflict
    if (!conflictState.matchesTerminalConflict(conflict, sessionId, requestedAction)) return null
    return conflict
  },

  _consumeAnyPomodoroTerminalConflict() {
    return this._readPomodoroTerminalConflict()
  },

  _ackPomodoroTerminalConflict(conflict) {
    if (!conflict || this._isPomodoroStorageError(conflict)) return false
    if (!this._safeRemovePomodoroStorage(POMODORO_TERMINAL_CONFLICT_KEY, 'terminal conflict ack')) {
      return false
    }
    if (
      this._pomodoroTerminalConflict &&
      this._pomodoroTerminalConflict.sessionId === conflict.sessionId &&
      this._pomodoroTerminalConflict.requestedAction === conflict.requestedAction
    ) {
      this._pomodoroTerminalConflict = null
    }
    return true
  },

  _handlePomodoroTerminalConflict(sessionId, conflict) {
    return handleTerminalConflict({
      isStorageError: (value) => this._isPomodoroStorageError(value),
      persistenceError: () => this._showPomodoroPersistenceError(),
      dropSessionActions: (id) => this._dropPendingPomodoroSessionActions(id),
      getStorage: (key, context) => this._safeGetPomodoroStorage(key, context),
      removeStorage: (key, context) => this._safeRemovePomodoroStorage(key, context),
      ackConflict: (c) => this._ackPomodoroTerminalConflict(c),
      get completionBreakSec() { return this._completionBreakSec },
      set completionBreakSec(v) { this._completionBreakSec = v },
      clearTimer: () => this._clearTimer(),
      setData: (data) => this.setData(data),
      resetIdle: () => this._resetToIdle(),
      showToast: (toast) => wx.showToast(toast),
      loadStats: () => this.loadTodayStats(),
    }, sessionId, conflict)
  },

  async _reconcilePendingPomodoroSyncFailure(pending, error) {
    if (!canReconcilePendingSync(error)) return false
    let active
    try {
      active = await api.get('/pomodoro/active')
    } catch (_) {
      return false
    }
    const decision = decidePendingSyncReconciliation(pending, error, active)
    if (decision.kind === 'not-reconcilable' || decision.kind === 'keep-pending') {
      return false
    }
    if (decision.kind === 'acknowledge') {
      if (!this._clearPendingPomodoroSync(pending)) return false
      this._maybeClearLocalPauseAdjustment(pending.sessionId)
      return true
    }
    if (decision.kind === 'retry-with-calibration') {
      this._updatePendingPomodoroSync(pending, {
        clientActionAt: api.now(),
        clockSkewRetries: decision.retries + 1,
      })
      return true
    }
    if (decision.kind === 'restore-active') {
      if (decision.clearTerminalCompletion) {
        const completionStored = this._safeGetPomodoroStorage('pomodoro_completion', 'stale terminal reconcile')
        if (!completionStored.ok) return false
        const completion = completionStored.value
        if (
          completion && completion.sessionId === pending.sessionId &&
          !this._safeRemovePomodoroStorage('pomodoro_completion', 'stale terminal reconcile')
        ) return false
        this._safeRemovePomodoroStorage('pomodoro_break', 'best-effort cleanup')
        this._completionBreakSec = null
        this.setData({ showCelebration: false, showEndConfirm: false })
      }
      if (this._pageVisible && this._restoreSession(active) === false) return false
      if (!this._clearPendingPomodoroSync(pending)) return false
      this._maybeClearLocalPauseAdjustment(pending.sessionId)
      return true
    }
    return this._dropPendingPomodoroSessionActions(pending.sessionId)
  },

  async _retryPendingPomodoroSync() {
    if (this._pendingSyncDrainPromise) return this._pendingSyncDrainPromise

    this._pendingSyncDrainPromise = (async () => {
      while (true) {
        const queue = this._getPendingPomodoroSyncQueue()
        if (queue === null) {
          this._showPomodoroPersistenceError()
          return false
        }
        if (!queue.length) {
          this._clearPendingPomodoroSyncRetryTimer(true)
          return true
        }
        const pending = queue[0]
        try {
          let body = {}
          const actionAtMs = Number(pending.clientActionAt)
          if (Number.isFinite(actionAtMs) && actionAtMs > 0) {
            try {
              body = { client_action_at: new Date(actionAtMs).toISOString() }
            } catch (_) {}
          }
          const response = await api.post(`/pomodoro/${pending.sessionId}/${pending.action}`, body)
          if (pending.action === 'complete' || pending.action === 'interrupt') {
            const expectedStatus = pending.action === 'complete' ? 'completed' : 'interrupted'
            if (response && response.status && response.status !== expectedStatus) {
              if (!this._recordPomodoroTerminalConflict(pending.sessionId, pending.action, response.status)) {
                // Server already committed a terminal state, but without a durable
                // conflict marker we must keep the pending mutation as the recovery
                // credential. A later retry is state-idempotent and can reconcile.
                this._showPomodoroPersistenceError()
                return false
              }
              if (!this._dropPendingPomodoroSessionActions(pending.sessionId)) {
                this._showPomodoroPersistenceError()
                return false
              }
              this._clearPendingPomodoroSyncRetryTimer(true)
              continue
            }
          }

          // Any successful mutation proves the server is reachable again, so the
          // next transient failure starts a fresh backoff sequence. Persistently
          // removing the head is part of acknowledging the server commit; if local
          // storage cannot do that, stop instead of spinning duplicate POSTs.
          this._clearPendingPomodoroSyncRetryTimer(true)
          if (!this._clearPendingPomodoroSync(pending)) {
            console.error('pomodoro pending action committed but local acknowledgement could not be persisted', pending)
            this._showPomodoroPersistenceError()
            return false
          }
          if (pending.action === 'pause' || pending.action === 'resume') {
            this._maybeClearLocalPauseAdjustment(pending.sessionId)
          }
        } catch (error) {
          const reconciled = await this._reconcilePendingPomodoroSyncFailure(pending, error)
          if (reconciled) {
            this._clearPendingPomodoroSyncRetryTimer(true)
            continue
          }
          this._schedulePendingPomodoroSyncRetry(error)
          return false
        }
      }
    })()

    try {
      return await this._pendingSyncDrainPromise
    } finally {
      this._pendingSyncDrainPromise = null
    }
  },

  async _completePomodoroWithRetry(sessionId, clientActionAt) {
    if (!sessionId) return false
    const pending = this._setPendingPomodoroSync('complete', sessionId, clientActionAt)
    if (!pending) {
      this._showPomodoroPersistenceError()
      return false
    }
    const synced = await this._retryPendingPomodoroSync()
    const conflict = this._readPomodoroTerminalConflict()
    if (this._isPomodoroStorageError(conflict)) return false
    return !!synced && !this._hasPendingPomodoroAction(sessionId, 'complete') && !(
      conflict && conflict.sessionId === sessionId && conflict.requestedAction === 'complete'
    )
  },

  async _interruptPomodoroWithRetry(sessionId, clientActionAt) {
    if (!sessionId) return false
    const pending = this._setPendingPomodoroSync('interrupt', sessionId, clientActionAt)
    if (!pending) {
      this._showPomodoroPersistenceError()
      return false
    }
    const synced = await this._retryPendingPomodoroSync()
    const conflict = this._readPomodoroTerminalConflict()
    if (this._isPomodoroStorageError(conflict)) return false
    return !!synced && !this._hasPendingPomodoroAction(sessionId, 'interrupt') && !(
      conflict && conflict.sessionId === sessionId && conflict.requestedAction === 'interrupt'
    )
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
    if (typeof now !== 'number') now = api.now()
    return calculateElapsedMs(now, this._timerState.sessionStartTime, this._timerState.totalPausedMs || 0)
  },

  _getEffectiveFreeElapsedMs(now) {
    if (typeof now !== 'number') now = api.now()
    const startTime = Number(this._timerState.sessionStartTime)
    if (!Number.isFinite(startTime) || startTime <= 0) return 0
    let totalPausedMs = Number(this._timerState.totalPausedMs || 0)
    totalPausedMs = this._mergeLocalPauseAdjustment(this._timerState.sessionId, totalPausedMs)
    return calculateElapsedMs(now, startTime, totalPausedMs)
  },

  _checkFreeTimerLimitAndAutoEnd() {
    if (!this.data.isFreeTimer || this.data.isPaused || this._freeTimerFinalizing) return false
    const elapsedMs = this._getEffectiveFreeElapsedMs()
    if (elapsedMs >= FREE_TIMER_MAX_MS) {
      this._autoFinishFreeTimer()
      return true
    }
    return false
  },

  async _autoFinishFreeTimer() {
    if (this._freeTimerFinalizing) return
    this._freeTimerFinalizing = true

    this._clearFreeTimerInterval()

    // Fix elapsed to exactly 5 hours for the record
    const elapsedSec = Math.floor(FREE_TIMER_MAX_MS / 1000)

    this._timerState.elapsedSec = elapsedSec
    const fmt = formatElapsedSec(elapsedSec)
    this.setData({ freeDisplayTime: fmt.display })

    wx.showToast({ title: '自由计时已达5小时上限，已自动结束', icon: 'none', duration: 2000 })

    await this._completeFreeTimerSession()

    this._freeTimerFinalizing = false
  },

  async _completeFreeTimerSession() {
    const sessionId = this._timerState.sessionId
    if (!sessionId) return
    this._clearFreeTimerInterval()
    const completedAt = api.now()

    this._completePomodoroWithRetry(sessionId, completedAt).then(synced => {
      const conflict = this._consumePomodoroTerminalConflict(sessionId, 'complete')
      if (conflict) {
        this._handlePomodoroTerminalConflict(sessionId, conflict)
        return
      }
      wx.showToast({
        title: synced ? '已记录本次专注' : '网络恢复后将自动同步',
        icon: 'none',
        duration: 2000,
      })
      if (synced) this.loadTodayStats()
    })

    // Do not keep the end-confirm UI blocked behind a 30s request timeout.
    this._resetToIdle()
  },

  _getEffectivePausedMsFromSession(session) {
    const serverBaseMs = (session.total_paused_sec || 0) * 1000
    let serverEffectiveMs = serverBaseMs

    if (session.paused_at) {
      const pausedAtMs = parseServerTime(session.paused_at)
      if (Number.isFinite(pausedAtMs)) {
        serverEffectiveMs += Math.max(0, api.now() - pausedAtMs)
      }
    }

    return this._mergeLocalPauseAdjustment(session.id, serverEffectiveMs)
  },

  _startTimer(totalSec, options = {}) {
    this._clearTimer()
    this._initCanvas(!options.reuseCanvas)
    const controller = createCountdownController({
      setTimeout: (fn, delay) => setTimeout(fn, delay),
      clearTimeout: timer => clearTimeout(timer),
      clearInterval: timer => clearInterval(timer),
    })
    this._timerController = controller

    // remainingMs has highest priority, then remainingSec, then this._timerState.remainingSec, then totalSec
    let remainMs
    if (Number.isFinite(options.remainingMs)) {
      remainMs = Math.max(0, options.remainingMs)
    } else {
      const remainSec = Number.isFinite(options.remainingSec)
        ? Math.max(0, options.remainingSec)
        : Math.max(0, this._timerState.remainingSec || totalSec)
      remainMs = remainSec * 1000
    }

    const totalMs = Math.max(1, totalSec * 1000)

    const displayRemainingSec = remainMs <= 0 ? 0 : Math.ceil(remainMs / 1000)
    const progress = totalMs > 0 ? remainMs / totalMs : 0
    const fmt = this._formatCountdownDisplay(displayRemainingSec)

    this._countdownTotalSec = totalSec
    this._countdownEndAt = api.now() + remainMs

    this._timerState.remainingSec = displayRemainingSec
    this._timerState.progress = progress
    const update = { displayMin: fmt.min, displaySec: fmt.sec, ringCanvasVisible: true }
    if (options.forceRunning) {
      update.isPaused = false
    }
    this.setData(update)

    const tick = () => {
      if (this.data.isPaused || this.data.showEndConfirm) {
        controller.stop()
        return
      }

      const remainingMs = Math.max(0, this._countdownEndAt - api.now())
      const displayRemainingSec = remainingMs <= 0 ? 0 : Math.ceil(remainingMs / 1000)
      const progress = totalMs > 0 ? remainingMs / totalMs : 0
      const fmt = this._formatCountdownDisplay(displayRemainingSec)

      if (
        displayRemainingSec !== this._timerState.remainingSec ||
        Math.abs(progress - this._timerState.progress) > 0.002
      ) {
        this._timerState.remainingSec = displayRemainingSec
        this._timerState.progress = progress
        this.setData({
          displayMin: fmt.min,
          displaySec: fmt.sec,
        })
      }

      this.drawRing(totalSec, this.data.phase === 'break')

      if (remainingMs <= 0) {
        this._clearTimer()
        this._onWorkComplete()
        return
      }

      const nextDelay = Math.max(80, Math.min(250, remainingMs % 1000 || 250))
      controller.scheduleTick(tick, nextDelay)
    }

    tick()
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
    const celebration = buildCompletionCelebration(sessionId, options, {
      data: this.data,
      mottoes: MOTTOES,
      nextCelebrationType: () => this._nextCelebrationType(),
      MathRandom: Math.random,
    })
    const { completionFlag, viewData, breakSec } = celebration
    // Re-assert attribution at completion so history keeps the task type even if
    // an earlier start-response mapping was interrupted by a restart.
    if (celebration.selectedTaskType) pomodoroTaskTypes.recordSession({ id: celebration.sessionId }, celebration.selectedTaskType)

    // Completion is final locally immediately. Remove every running snapshot
    // before showing the animation so onHide cannot persist/resurrect this session.
    this._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_pause', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_free_pause', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_pause_adjustment', 'best-effort cleanup')
    this._confirmTimerSnapshot = null
    this._timerState.endConfirmMode = ''
    this._completionBreakSec = breakSec

    this._safeSetPomodoroStorage('pomodoro_completion', completionFlag, 'completion marker')

    // Invalidate the native canvas before the running wx:if block disappears.
    this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
    this._canvasInitPending = false
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null
    this._pendingDraw = null

    this.setData(viewData)
  },

  async _onWorkComplete() {
    const sessionId = this._timerState.sessionId
    if (!sessionId) {
      this._resetToIdle()
      return
    }

    const completedAt = api.now()
    this._clearTimer()
    wx.vibrateLong()
    this._completePomodoroWithRetry(sessionId, completedAt).then(synced => {
      const conflict = this._consumePomodoroTerminalConflict(sessionId, 'complete')
      if (conflict) {
        this._handlePomodoroTerminalConflict(sessionId, conflict)
        return
      }
      if (synced) {
        this.loadTodayStats()
      } else {
        wx.showToast({ title: '已完成，网络恢复后自动同步', icon: 'none' })
      }
    })

    this._showCompletionCelebration(sessionId)
  },

  dismissCelebration() {
    const completionStored = this._safeGetPomodoroStorage('pomodoro_completion', 'dismiss celebration')
    if (!completionStored.ok) {
      this._showPomodoroPersistenceError()
      return
    }
    const completionFlag = completionStored.value
    const breakSec = resolveBreakSec(completionFlag, this._completionBreakSec, this.data)
    this._safeRemovePomodoroStorage('pomodoro_completion', 'best-effort cleanup')
    this._completionBreakSec = null
    this.setData({ showCelebration: false })
    if (breakSec > 0) {
      this._startBreak(breakSec)
    } else {
      this._resetToIdle()
    }
  },

  /* ==================== Break Timer ==================== */

  _startBreak(totalSec, options = {}) {
    const originalTotalSec = Math.max(1, Number(totalSec) || 1)
    const breakStartTime = Number.isFinite(options.startTime) ? options.startTime : api.now()
    const totalMs = originalTotalSec * 1000
    const naturalRemainingMs = Math.max(0, breakStartTime + totalMs - api.now())
    const remainingMs = Number.isFinite(options.remainingMs)
      ? Math.max(0, Math.min(totalMs, options.remainingMs))
      : naturalRemainingMs

    if (remainingMs <= 0) {
      this._safeRemovePomodoroStorage('pomodoro_break', 'best-effort cleanup')
      this._resetToIdle()
      return
    }

    // Preserve the original break start/total across page restores. Re-basing the
    // timer to `remaining` made the dial jump back to a full ring on every onShow.
    this._safeSetPomodoroStorage('pomodoro_break', { startTime: breakStartTime, totalSec: originalTotalSec }, 'break snapshot')
    this._timerState.breakStartTime = breakStartTime
    this._timerState.remainingSec = Math.ceil(remainingMs / 1000)
    this._timerState.progress = remainingMs / totalMs
    const firstFmt = this._formatCountdownDisplay(this._timerState.remainingSec)
    this.setData({
      phase: PHASE.BREAK,
      ringCanvasVisible: true,
      displayMin: firstFmt.min,
      displaySec: firstFmt.sec,
    })
    this._clearTimer()
    this._initCanvas(true)
    this._countdownTotalSec = originalTotalSec
    this._countdownEndAt = breakStartTime + totalMs
    this.drawRing(originalTotalSec, true)

    const tick = () => {
      const currentRemainingMs = Math.max(0, this._countdownEndAt - api.now())
      const displayRemainingSec = currentRemainingMs <= 0 ? 0 : Math.ceil(currentRemainingMs / 1000)
      const progress = currentRemainingMs / totalMs
      const fmt = this._formatCountdownDisplay(displayRemainingSec)

      if (
        displayRemainingSec !== this._timerState.remainingSec ||
        Math.abs(progress - this._timerState.progress) > 0.002
      ) {
        this._timerState.remainingSec = displayRemainingSec
        this._timerState.progress = progress
        this.setData({ displayMin: fmt.min, displaySec: fmt.sec })
      }
      this.drawRing(originalTotalSec, true)

      if (currentRemainingMs <= 0) {
        this._clearTimer()
        this._safeRemovePomodoroStorage('pomodoro_break', 'best-effort cleanup')
        this._resetToIdle()
        return
      }

      const nextDelay = Math.max(80, Math.min(250, currentRemainingMs % 1000 || 250))
      if (!this._timerController) {
        this._timerController = createCountdownController({
          setTimeout: (fn, delay) => setTimeout(fn, delay),
          clearTimeout: timer => clearTimeout(timer),
          clearInterval: timer => clearInterval(timer),
        })
      }
      this._timerController.scheduleTick(tick, nextDelay)
    }
    tick()
  },

  skipBreak() {
    this._clearTimer()
    this._safeRemovePomodoroStorage('pomodoro_break', 'best-effort cleanup')
    this._resetToIdle()
  },

  /* ==================== Session Restore ==================== */

  _canLightSyncActive(active) {
    if (!this._timerState.sessionId) return false
    if (active.id !== this._timerState.sessionId) return false
    if (this.data.phase !== PHASE.RUNNING) return false
    if ((active.status === 'paused') !== this.data.isPaused) return false
    if ((active.preset === 'free') !== this.data.isFreeTimer) return false
    if (typeof this._timerState.sessionStartTime !== 'number' || this._timerState.sessionStartTime <= 0) return false
    return true
  },

  _syncActiveSessionLight(active, failClosed = false) {
    const now = api.now()
    const serverStartTime = parseServerTime(active.start_time)
    if (Number.isFinite(serverStartTime) && serverStartTime > 0) {
      this._timerState.sessionStartTime = serverStartTime
    }
    const allocationMode = active.allocation_mode === 'equal_408_core_v1'
      ? 'equal_408_core_v1'
      : 'single'
    if (allocationMode !== this.data.allocationMode) {
      const subjectId = active.subject_id || this.data.selectedSubjectId
      const subject = (this.data.subjects || []).find(
        item => Number(item.id) === Number(subjectId)
      ) || this.data.selectedSubject
      this.setData({
        allocationMode,
        selectedSubject: subject
          ? { ...subject, _isAggregate: allocationMode === 'equal_408_core_v1' }
          : subject,
      })
      this._updateComputedFields()
    }

    const serverPausedMs = Math.max(0, Number(active.total_paused_sec || 0) * 1000)
    const localPausedMs = Math.max(0, Number(this._timerState.totalPausedMs || 0))
    const totalPausedMs = this._mergeLocalPauseAdjustment(
      this._timerState.sessionId,
      Math.max(serverPausedMs, localPausedMs),
      failClosed
    )
    if (totalPausedMs === null) {
      if (failClosed) this._showPomodoroPersistenceError()
      return false
    }
    this._timerState.totalPausedMs = totalPausedMs

    if (this.data.isFreeTimer) {
      if (!this._canvasReady || !this._ctx) {
        this._timerState.progress = 1
        wx.nextTick(() => {
          if (!this._pageVisible || this.data.phase !== PHASE.RUNNING || !this.data.isFreeTimer) return
          this._initCanvas(true)
          this.drawRing(0, false)
        })
      }
      if (!this.data.isPaused) {
        const elapsedMs = Math.max(0, now - this._timerState.sessionStartTime - totalPausedMs)
        const cappedMs = Math.min(elapsedMs, FREE_TIMER_MAX_MS)
        const elapsed = Math.floor(cappedMs / 1000)
        if (elapsed !== this._timerState.elapsedSec) {
          const fmt = formatElapsedSec(elapsed)
          this._timerState.elapsedSec = elapsed
          this.setData({ freeDisplayTime: fmt.display })
        }
        if (elapsedMs >= FREE_TIMER_MAX_MS) {
          this._autoFinishFreeTimer()
          return true
        }
        // onHide clears the interval, so onShow must always restart it.
        this._startFreeTimerInterval()
      }
      return true
    }

    const totalSec = this.data.selectedPreset === 'debug' ? 10 : (this.data.workDuration ?? 25) * 60
    if (this.data.isPaused) {
      if (!this._canvasReady || !this._ctx) {
        wx.nextTick(() => {
          if (!this._pageVisible || this.data.phase !== PHASE.RUNNING || !this.data.isPaused) return
          this._initCanvas(true)
          this.drawRing(totalSec, false)
        })
      }
      return true
    }

    const elapsedMs = Math.max(0, now - this._timerState.sessionStartTime - totalPausedMs)
    const remainingMs = Math.max(0, totalSec * 1000 - elapsedMs)
    if (remainingMs <= 0) {
      this._clearTimer()
      this._onWorkComplete()
      return true
    }

    // onHide clears the timeout. Restart from wall-clock-derived remaining time
    // instead of repainting only one frame and leaving the countdown stopped.
    this._startTimer(totalSec, { remainingMs, forceRunning: true, reuseCanvas: true })
    return true
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
    // Free timer recovery
    if (session.preset === 'free') {
      return this._restoreFreeSession(session)
    }

    // Guard: if confirm snapshot is active, don't overwrite with server state.
    // A storage read failure is not equivalent to "no confirm snapshot".
    let confirmSnapshot = this._confirmTimerSnapshot
    if (!confirmSnapshot) {
      const storedConfirm = this._safeGetPomodoroStorage('pomodoro_confirm_pause', 'restore countdown confirm')
      if (!storedConfirm.ok) {
        this._showPomodoroPersistenceError()
        return false
      }
      confirmSnapshot = storedConfirm.value
    }
    if (confirmSnapshot && confirmSnapshot.sessionId === session.id && this.data.showEndConfirm) {
      return true
    }

    const startTime = parseServerTime(session.start_time)
    const totalSec = session.work_duration * 60

    if (!Number.isFinite(startTime) || !Number.isFinite(totalSec) || totalSec <= 0) {
      this._safeRemovePomodoroStorage('pomodoro_pause', 'best-effort cleanup')
      this._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
      this._resetToIdle()
      wx.showToast({ title: '番茄钟状态异常，已重置', icon: 'none' })
      return true
    }

    // Compute effective paused ms: server base + current segment + local adjustment
    const storedPause = this._safeGetPomodoroStorage('pomodoro_pause', 'restore countdown pause')
    if (!storedPause.ok) {
      this._showPomodoroPersistenceError()
      return false
    }
    const pausedAtMs = session.paused_at ? parseServerTime(session.paused_at) : null
    let totalPausedMs = resolvePausedMs({
      serverPausedSec: session.total_paused_sec || 0,
      savedPause: storedPause.value,
      pausedAtMs,
      now: api.now(),
      sessionId: session.id,
    }).totalPausedMs

    // Apply local pause adjustment (e.g. from cancelEndConfirm). During cold
    // restore this is critical state: unreadable storage must stop reconciliation
    // instead of silently treating the adjustment as zero.
    totalPausedMs = this._mergeLocalPauseAdjustment(session.id, totalPausedMs, true)
    if (totalPausedMs === null) {
      this._showPomodoroPersistenceError()
      return false
    }

    const restore = computeCountdownRestore({
      serverPausedSec: session.total_paused_sec || 0,
      savedPause: storedPause.value,
      pausedAtMs,
      now: api.now(),
      startTime,
      totalSec,
      sessionId: session.id,
    })
    totalPausedMs = restore.totalPausedMs
    const isPaused = restore.isPaused
    const remaining = restore.remaining
    const subject = resolveRestoredSubject({
      session,
      subjects: this.data.subjects,
      lookupSubjectIdByCode: code => this._lookupSubjectIdByCode(code),
    })
    const { subjectId, selectedSubject, aggregate: aggregateSession } = subject
    const sessionTaskType = pomodoroTaskTypes.typeForSession(session)
    const activeTaskType = sessionTaskType || ''
    const activeTaskTypeLabel = sessionTaskType ? pomodoroTaskTypes.label(sessionTaskType) : '未分类'
    // Old sessions have no task-type metadata. Show them as unclassified rather
    // than borrowing the user's current selector and corrupting history semantics.
    if (sessionTaskType) pomodoroTaskTypes.recordSession(session, sessionTaskType)

    if (remaining <= 0) {
      this._safeRemovePomodoroStorage('pomodoro_pause', 'best-effort cleanup')
      this._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
      const completedAt = restore.completedAt
      this._completePomodoroWithRetry(session.id, completedAt).then(synced => {
        const conflict = this._consumePomodoroTerminalConflict(session.id, 'complete')
        if (conflict) {
          this._handlePomodoroTerminalConflict(session.id, conflict)
          return
        }
        if (synced) this.loadTodayStats()
      }).catch(() => {})
      this._timerState.totalPausedMs = 0
      this._timerState.pauseStartTime = null
      this.setData({
        selectedSubjectId: subjectId,
        selectedSubject: subjectId ? selectedSubject : null,
        allocationMode: aggregateSession ? 'equal_408_core_v1' : 'single',
        selectedTaskType: activeTaskType,
        selectedTaskTypeLabel: activeTaskTypeLabel,
        selectedPreset: session.preset || 'standard',
        workDuration: session.work_duration,
        breakDuration: session.break_duration,
        isPaused: false,
      })
      this._updateComputedFields()
      this.loadTodayStats()
      wx.vibrateLong()
      this._showCompletionCelebration(session.id, {
        selectedPreset: session.preset || 'standard',
        workDuration: session.work_duration,
        breakDuration: session.break_duration,
        selectedSubjectId: subjectId,
        selectedSubject: subjectId ? selectedSubject : null,
        selectedTaskType: activeTaskType,
        selectedTaskTypeLabel: activeTaskTypeLabel,
      })
      return true
    }

    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.remainingSec = remaining
    this._timerState.totalPausedMs = totalPausedMs
    this._timerState.pauseStartTime = isPaused ? api.now() : null
    this._timerState.progress = restore.progress
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      selectedSubjectId: subjectId,
      selectedSubject: subjectId ? selectedSubject : null,
      allocationMode: aggregateSession ? 'equal_408_core_v1' : 'single',
      selectedTaskType: activeTaskType,
      selectedTaskTypeLabel: activeTaskTypeLabel,
      selectedPreset: session.preset || 'standard',
      workDuration: session.work_duration,
      breakDuration: session.break_duration,
      displayMin: String(Math.floor(remaining / 60)).padStart(2, '0'),
      displaySec: String(remaining % 60).padStart(2, '0'),
      isPaused: isPaused,
    })

    if (isPaused) {
      this._safeSetPomodoroStorage('pomodoro_pause', {
        totalPausedMs: totalPausedMs,
        pauseStartTime: api.now(),
        sessionId: session.id,
      })
      // Draw ring at the paused progress — canvas never destroyed with hidden
      wx.nextTick(() => {
        this._initCanvas(true)
        this.drawRing(totalSec, false)
      })
    } else {
      this._startTimer(totalSec)
    }
    this._updateComputedFields()
    return true
  },

  _restoreFreeSession(session) {
    const startTime = parseServerTime(session.start_time)
    if (!Number.isFinite(startTime) || startTime <= 0) {
      this._safeRemovePomodoroStorage('pomodoro_free_pause', 'best-effort cleanup')
      this._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
      this._resetToIdle()
      return true
    }

    const storedPause = this._safeGetPomodoroStorage('pomodoro_free_pause', 'restore free pause')
    if (!storedPause.ok) {
      this._showPomodoroPersistenceError()
      return false
    }
    const pausedAtMs = session.paused_at ? parseServerTime(session.paused_at) : null
    let totalPausedMs = resolvePausedMs({
      serverPausedSec: session.total_paused_sec || 0,
      savedPause: storedPause.value,
      pausedAtMs,
      now: api.now(),
      sessionId: session.id,
    }).totalPausedMs
    totalPausedMs = this._mergeLocalPauseAdjustment(session.id, totalPausedMs, true)
    if (totalPausedMs === null) {
      this._showPomodoroPersistenceError()
      return false
    }

    // Server start_time remains the only clock origin during cold restore too;
    // legacy freeDisplayOffsetMs caches are intentionally ignored.
    this._timerState.sessionId = session.id
    this._timerState.sessionStartTime = startTime
    this._timerState.totalPausedMs = totalPausedMs
    this._timerState.freeDisplayOffsetMs = 0

    const restore = computeFreeRestore({
      serverPausedSec: session.total_paused_sec || 0,
      savedPause: storedPause.value,
      pausedAtMs,
      now: api.now(),
      startTime,
      maxMs: FREE_TIMER_MAX_MS,
      sessionId: session.id,
    })
    totalPausedMs = restore.totalPausedMs
    const isPaused = restore.isPaused
    const elapsed = restore.elapsed
    const fmt = formatElapsedSec(elapsed)

    this._timerState.pauseStartTime = isPaused ? api.now() : null

    const subject = resolveRestoredSubject({
      session,
      subjects: this.data.subjects,
      lookupSubjectIdByCode: code => this._lookupSubjectIdByCode(code),
    })
    const { subjectId, selectedSubject, aggregate: aggregateSession } = subject
    const sessionTaskType = pomodoroTaskTypes.typeForSession(session)
    const activeTaskType = sessionTaskType || ''
    const activeTaskTypeLabel = sessionTaskType ? pomodoroTaskTypes.label(sessionTaskType) : '未分类'
    if (sessionTaskType) pomodoroTaskTypes.recordSession(session, sessionTaskType)

    this._clearTimer()
    this._timerState.elapsedSec = elapsed
    this._timerState.freeFriendlyText = fmt.friendly
    this._timerState.progress = 1
    this.setData({
      phase: PHASE.RUNNING,
      ringCanvasVisible: true,
      isFreeTimer: true,
      selectedSubjectId: subjectId,
      selectedSubject,
      allocationMode: aggregateSession ? 'equal_408_core_v1' : 'single',
      selectedTaskType: activeTaskType,
      selectedTaskTypeLabel: activeTaskTypeLabel,
      selectedPreset: 'free',
      workDuration: 0,
      breakDuration: 0,
      isPaused: isPaused,
      freeDisplayTime: fmt.display,
      showEndConfirm: false,
    })
    this._updateComputedFields()

    wx.nextTick(() => {
      this._initCanvas(true)
      this.drawRing(0, false)
    })

    if (!isPaused) {
      this._startFreeTimerInterval()
      this._checkFreeTimerLimitAndAutoEnd()
    }
    return true
  },

  _restoreBreak() {
    try {
      const saved = wx.getStorageSync('pomodoro_break')
      if (!saved || !saved.startTime || !saved.totalSec) return false
      const totalMs = Math.max(1, Number(saved.totalSec) * 1000)
      const remainingMs = Math.max(0, Number(saved.startTime) + totalMs - api.now())
      if (remainingMs <= 0) {
        this._safeRemovePomodoroStorage('pomodoro_break', 'best-effort cleanup')
        this._resetToIdle()
        return false
      }
      this._startBreak(Number(saved.totalSec), {
        startTime: Number(saved.startTime),
        remainingMs,
      })
      return true
    } catch (_) {
      return false
    }
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
    if (!force && ((this._canvasReady && this._ctx) || this._canvasInitPending)) return

    // Every forced rebuild invalidates older selector-query callbacks. On real
    // devices a callback from the previous page/layout can arrive late and bind
    // the 2D context to a stale native-canvas position, which makes the ring jump
    // to the top of the page after re-entering Pomodoro.
    const initSeq = (this._canvasInitSeq || 0) + 1
    this._canvasInitSeq = initSeq
    this._canvasInitPending = true
    this._canvasReady = false
    this._ctx = null
    this._ringCache = null // 清除缓存的渐变/几何
    if (this.data.ringCanvasPaintReady) {
      this.setData({ ringCanvasPaintReady: false })
    }

    // A rebuilt canvas is blank. Reset draw-throttle state as well, otherwise
    // the first paint can be skipped because progress barely changed.
    this._lastDrawnProgress = undefined
    this._lastDrawnIsBreak = undefined
    this._lastDrawnAt = 0
    this._scheduleCanvasInit(0, initSeq, null)
  },

  _scheduleCanvasInit(retryCount, initSeq, previousRect) {
    if (initSeq !== this._canvasInitSeq) return
    if (retryCount > CANVAS_INIT_MAX_RETRIES) {
      this._canvasInitPending = false
      return
    }

    wx.nextTick(() => {
      if (initSeq !== this._canvasInitSeq) return
      if (!this._pageVisible) {
        this._canvasInitPending = false
        return
      }

      const query = wx.createSelectorQuery().in(this)
      query.select('.ring-stage').boundingClientRect()
      query.select('#progress-ring').fields({ node: true, size: true, rect: true })
      query.exec((res) => {
        if (initSeq !== this._canvasInitSeq) return

        const stageRect = res && res[0]
        const canvasInfo = res && res[1]
        const layout = evaluateCanvasLayout(stageRect, canvasInfo, previousRect)
        if (layout.status !== 'ready') {
          const delay = canvasRetryDelay(retryCount)
          setTimeout(() => this._scheduleCanvasInit(retryCount + 1, initSeq, previousRect), delay)
          return
        }

        const canvas = canvasInfo.node
        const windowInfo = wx.getWindowInfo ? wx.getWindowInfo() : {}
        const setup = buildCanvasSetup(layout.rect, windowInfo.pixelRatio)
        this._dpr = setup.dpr
        this._canvasSize = setup.size
        canvas.width = setup.pixelWidth
        canvas.height = setup.pixelHeight
        const ctx = canvas.getContext('2d')
        ctx.setTransform(setup.dpr, 0, 0, setup.dpr, 0, 0)
        this._ctx = ctx
        this._canvasReady = true
        this._canvasInitPending = false
        this._ringCache = null // 重建后缓存失效
        if (this._pendingDraw) {
          const pending = this._pendingDraw
          this._pendingDraw = null
          this.drawRing(pending.totalSec, pending.isBreak)
        }
      })
    })
  },

  _buildRingCache(isBreak) {
    return buildRingCache(this._ctx, this._canvasSize, isBreak, this.data.isFreeTimer)
  },

  drawRing(totalSec, isBreak) {
    if (!this._ctx) {
      this._pendingDraw = { totalSec, isBreak }
      // Self-heal after an unusually slow native-canvas mount. If the first
      // initialization exhausted its retry window, the next timer tick retries
      // automatically instead of leaving a permanently blank ring.
      if (this._pageVisible && !this.data.showEndConfirm && this.data.ringCanvasVisible && !this._canvasInitPending) {
        this._initCanvas(false)
      }
      return
    }
    var ctx = this._ctx
    var progress = this._timerState.progress
    var now = api.now()
    // Keep throttling expensive canvas work, but guarantee a visible refresh at
    // least about once per second. The old fixed 1/360 threshold meant a 25-min
    // ring could wait ~4.2s and a 50-min ring ~8.3s before moving.
    if (!shouldDrawRing(progress, isBreak, {
      progress: this._lastDrawnProgress,
      isBreak: this._lastDrawnIsBreak,
      totalSec,
      at: this._lastDrawnAt,
    }, now)) return
    this._lastDrawnProgress = progress
    this._lastDrawnIsBreak = isBreak
    this._lastDrawnAt = now

    // 缓存渐变和几何，仅在 isBreak/freeTimer 切换时重建
    var cacheKey = (isBreak ? 'break' : (this.data.isFreeTimer ? 'free' : 'focus')) + '|' + this.data.themeMode
    if (!this._ringCache || this._ringCache._key !== cacheKey) {
      this._ringCache = this._buildRingCache(isBreak)
      if (this._ringCache) this._ringCache._key = cacheKey
    }
    var cache = this._ringCache
    if (!cache) return

    var center = cache.center
    var radius = cache.radius
    var lineWidth = cache.lineWidth
    var colors = cache.colors

    ctx.clearRect(0, 0, cache.size, cache.size)

    if (progress > 0) {
      ctx.beginPath()
      ctx.strokeStyle = cache.glowGrad
      ctx.lineWidth = lineWidth + 14
      ctx.lineCap = 'round'
      ctx.globalAlpha = 0.18
      ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
      ctx.stroke()
      ctx.globalAlpha = 1
    }

    ctx.beginPath()
    ctx.strokeStyle = this.data.themeMode === 'light' ? 'rgba(21,51,35,0.12)' : 'rgba(255,255,255,0.06)'
    ctx.lineWidth = lineWidth
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.stroke()

    ctx.beginPath()
    ctx.strokeStyle = cache.grad
    ctx.lineWidth = lineWidth
    ctx.lineCap = 'round'
    ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * progress)
    ctx.stroke()

    if (progress > 0 && progress < 1) {
      var endAngle = -Math.PI / 2 + Math.PI * 2 * progress
      var endX = center + radius * Math.cos(endAngle)
      var endY = center + radius * Math.sin(endAngle)
      ctx.beginPath()
      ctx.fillStyle = colors.dot
      ctx.arc(endX, endY, lineWidth / 2 + 1, 0, Math.PI * 2)
      ctx.fill()
    }

    // Only reveal the canvas after a successful paint at a stable layout
    // position. Until then the glow/center text remain visible, preventing a
    // one-frame native-canvas flash at the top of the page.
    if (!this.data.ringCanvasPaintReady) {
      this.setData({ ringCanvasPaintReady: true })
    }
  },

  _resetToIdle() {
    this._clearFreeTimerInterval()
    this._confirmTimerSnapshot = null
    // Invalidate any selector callback that still points at the running-state
    // canvas before the wx:if block is removed.
    this._canvasInitSeq = (this._canvasInitSeq || 0) + 1
    this._canvasReady = false
    this._canvasInitPending = false
    this._ctx = null
    this._pendingDraw = null
    this._lastDrawnProgress = undefined
    this._lastDrawnIsBreak = undefined
    this._ringCache = null
    this._timerState = this._createTimerState()
    this._safeRemovePomodoroStorage('pomodoro_break', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_completion', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_pause', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_free_pause', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_running_state', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_confirm_pause', 'best-effort cleanup')
    this._safeRemovePomodoroStorage('pomodoro_pause_adjustment', 'best-effort cleanup')
    const preferredTaskType = pomodoroTaskTypes.getSelected()
    this.setData({
      phase: PHASE.IDLE,
      selectedTaskType: preferredTaskType,
      selectedTaskTypeLabel: pomodoroTaskTypes.label(preferredTaskType),
      displayMin: '00',
      displaySec: '00',
      isPaused: false,
      isFreeTimer: false,
      freeDisplayTime: '00:00:00',
      showEndConfirm: false,
      ringCanvasPaintReady: false,
      endConfirmTheme: '',
      endConfirmTitle: '',
      endConfirmText: '',
      endConfirmLine1: '',
      endConfirmLine2: '',
      endConfirmLine3: '',
    })
    this._completionBreakSec = null
    this._updateComputedFields()
  },

  /* ==================== Stats ==================== */

  async loadTodayStats() {
    const requestSeq = (this._statsRequestSeq || 0) + 1
    this._statsRequestSeq = requestSeq
    try {
      const stats = await api.get('/pomodoro/stats')
      // Multiple lifecycle/conflict paths can refresh stats concurrently. Only the
      // newest request may update UI, so a slower pre-completion response cannot
      // overwrite a newer post-completion total.
      if (requestSeq !== this._statsRequestSeq) return
      const m = Math.floor((stats.today_duration_sec || 0) / 60)
      this._timerState.todayDurationSec = stats.today_duration_sec || 0
      this.setData({
        todaySessions: stats.today_sessions || 0,
        todayDurationText: m >= 60 ? `${Math.floor(m / 60)}时${m % 60}分` : `${m}分钟`,
      })
    } catch (_) {}
  },

  goStats() {
    this._navigatingToStats = true
    wx.navigateTo({ url: '/subpackages/productivity/pomodoro-stats/index' })
  },


  /* ==================== Theme ==================== */

  _getThemeViewModel(mode) {
    const themeMode = pomodoroTheme.normalizeTheme(mode)
    const isLight = themeMode === 'light'
    return {
      themeMode,
      sliderBlockColor: isLight ? '#153323' : '#ffffff',
      sliderTrackColor: isLight ? 'rgba(21,51,35,0.12)' : 'rgba(255,255,255,0.06)',
      celebrationTheme: isLight ? 'light' : 'dark',
    }
  },

  _syncThemeFromStorage() {
    const themeMode = pomodoroTheme.getTheme()
    pomodoroTheme.applyNativeTheme(themeMode)
    if (themeMode === this.data.themeMode) return
    this._applyTheme(themeMode, false, false)
  },

  _applyTheme(mode, persist, animate) {
    const themeMode = pomodoroTheme.normalizeTheme(mode)
    if (persist) pomodoroTheme.setTheme(themeMode)
    pomodoroTheme.applyNativeTheme(themeMode)

    if (this._themeSwitchTimer) {
      clearTimeout(this._themeSwitchTimer)
      this._themeSwitchTimer = null
    }

    const patch = this._getThemeViewModel(themeMode)
    if (animate) patch.themeSwitching = true
    this.setData(patch, () => {
      this._ringCache = null
      this._lastDrawnProgress = undefined
      this._lastDrawnIsBreak = undefined
      if ((this.data.phase === PHASE.RUNNING || this.data.phase === PHASE.BREAK) &&
          this.data.ringCanvasVisible && !this.data.showEndConfirm) {
        wx.nextTick(() => this.drawRing(this._getCurrentTotalSec(), this.data.phase === PHASE.BREAK))
      }
    })

    if (animate) {
      this._themeSwitchTimer = setTimeout(() => {
        this._themeSwitchTimer = null
        this.setData({ themeSwitching: false })
      }, 520)
    }
  },

  toggleTheme() {
    const next = this.data.themeMode === 'dark' ? 'light' : 'dark'
    this._applyTheme(next, true, true)
  },

  /* ==================== Font Size Toggle ==================== */

  cycleFontSize() {
    const levels = ['medium', 'large']
    const current = this.data.fontSizeLevel
    const idx = levels.indexOf(current)
    const next = levels[(idx + 1) % levels.length]
    this.setData({ fontSizeLevel: next })
    wx.setStorageSync('pomodoro_font_size', next)
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
    const { getSubjectName } = require('./utils/subject-meta')
    const s = this.data.subjects.find(s => s.code === key)
    return s ? s.name : getSubjectName(key)
  },

  subjectColor(key) {
    return '#3B82F6'
  },


  presetLabel(key) {
    const p = PRESETS.find(p => p.key === key)
    return p ? p.label : key
  },

  _nextCelebrationType() {
    var types = ['excellent', 'award', 'thumbsUp']
    var idx = wx.getStorageSync('pomodoro_anim_idx') || 0
    var next = (idx + 1) % types.length
    wx.setStorageSync('pomodoro_anim_idx', next)
    return types[idx]
  },

  getDateStr() {
    const d = getChinaWallParts(api.now())
    const week = ['日', '一', '二', '三', '四', '五', '六']
    return `${d.month}月${d.day}日 星期${week[d.weekday]}`
  },

  _getExamDays() {
    const nowParts = getChinaWallParts(api.now())
    const todayStart = getChinaDayStartUtcMs(`${nowParts.year}-${String(nowParts.month).padStart(2, '0')}-${String(nowParts.day).padStart(2, '0')}`)
    const getExamDayUtc = (year) => {
      const dec31 = new Date(Date.UTC(year, 11, 31))
      const dayOfWeek = dec31.getUTCDay()
      const lastSaturday = 31 - ((dayOfWeek - 6 + 7) % 7)
      const targetDay = lastSaturday - 7
      return Date.UTC(year, 11, targetDay) - 8 * 60 * 60 * 1000
    }
    let examStart = getExamDayUtc(nowParts.year)
    if (examStart < todayStart) examStart = getExamDayUtc(nowParts.year + 1)
    return Math.max(0, Math.round((examStart - todayStart) / (24 * 60 * 60 * 1000)))
  },

})

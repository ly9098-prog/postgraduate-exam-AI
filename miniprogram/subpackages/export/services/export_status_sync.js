/**
 * ExportStatusSyncManager — page-level WebSocket + calibration polling for export tasks.
 *
 * Design:
 * - One WebSocket per page instance (not per task).
 * - Routes incoming status events by task_id to registered callbacks.
 * - **Calibration polling** runs even when WS is healthy, at reduced frequency,
 *   to recover from missed events (cross-process loss, backend restart, page background).
 * - Uses ``_wsOpened`` flag instead of ``WebSocket.OPEN`` (WeChat SocketTask is not
 *   a browser WebSocket and the global ``WebSocket`` constant may not exist).
 * - Transition protection: never let a delayed response override a newer terminal state.
 *
 * Usage:
 *   const sync = new ExportStatusSyncManager({
 *     onUpdate: (taskId, taskData) => { ... },
 *     onCalibrate: (nonTerminalIds) => { ... },
 *     onError: (err) => { ... },
 *   })
 *   sync.setTaskIds([42, 43])
 *   sync.start()
 *   // ... page onHide:
 *   sync.onHide()
 *   // ... page onShow:
 *   sync.onShow()
 *   // ... done:
 *   sync.stop()
 */
const api = require('../../../utils/api')
const config = require('../../../config')
const storage = require('../../../utils/storage')

const TERMINAL_STATES = ['completed', 'failed', 'expired']
const WS_HEARTBEAT_INTERVAL = 25000
const CALIBRATION_INTERVAL_WS = 12000  // WS is primary; DB calibration is only a missed-event safety net
const CALIBRATION_INTERVAL_FALLBACK = 3000  // polling interval when WS is unavailable

/**
 * State priority: a higher index means "more terminal".
 * Used to reject stale updates that would regress a task.
 */
const STATE_RANK = {
  pending: 0,
  processing: 1,
  completed: 2,
  failed: 2,
  expired: 2,
}

class ExportStatusSyncManager {
  /**
   * @param {object} options
   * @param {function(number, object)} [options.onUpdate] - Called with (taskId, data) on status change
   * @param {function(Error)} [options.onError] - Called on non-fatal errors
   * @param {number} [options.pollIntervalMs=3000] - Fallback polling interval in ms
   */
  constructor(options = {}) {
    this._taskIds = new Set()
    this._onUpdate = options.onUpdate || null
    this._onError = options.onError || null
    this._pollIntervalMs = options.pollIntervalMs || CALIBRATION_INTERVAL_FALLBACK

    // Track per-task status for transition protection
    this._taskStatuses = {}  // taskId -> status string

    // Internal state
    this._stopped = false
    this._ws = null
    this._wsOpened = false
    this._pollTimer = null
    this._calibrationPromise = null
    this._reconnectTimer = null
    this._heartbeatTimer = null
    this._consecutiveErrors = 0
    this._maxConsecutiveErrors = 5
    this._hidden = false
    this._reconnectAttempts = 0
    this._maxReconnectAttempts = 5
    // One logical trace spans WS reconnects and calibration/polling requests.
    this._traceId = api.createTraceId()
  }

  // ── Public API ──

  /** Add a task ID to monitor. No-op if already added. */
  addTask(taskId) {
    if (typeof taskId !== 'number') return
    this._taskIds.add(taskId)
  }

  /** Remove a task ID from monitoring. */
  removeTask(taskId) {
    this._taskIds.delete(taskId)
    delete this._taskStatuses[taskId]
  }

  /** Replace all tracked task IDs. Preserves known statuses for existing IDs. */
  setTaskIds(ids) {
    const newSet = new Set(ids.filter(id => typeof id === 'number'))
    // Clean up statuses for removed IDs
    const previousTaskIds = Array.from(this._taskIds)
    for (let taskIndex = 0; taskIndex < previousTaskIds.length; taskIndex++) {
      const tid = previousTaskIds[taskIndex]
      if (!newSet.has(tid)) {
        delete this._taskStatuses[tid]
      }
    }
    this._taskIds = newSet
  }

  /** Start or resume synchronisation. Safe to call multiple times. */
  start() {
    if (this._stopped) return
    this._hidden = false
    this._reconnectAttempts = 0

    // Only connect if there are tasks to monitor
    if (this._taskIds.size === 0) return

    // Don't reconnect if WS is already healthy
    if (this._wsOpened) return

    this._connectWebSocket()
  }

  /**
   * Temporarily suspend synchronisation while keeping the manager reusable.
   * This is used when all current tasks are terminal; a later retry or
   * re-export can add a new task and call start() on the same page instance.
   */
  pause() {
    if (this._stopped) return
    this._hidden = false
    this._cleanupTransient()
    this._consecutiveErrors = 0
    this._reconnectAttempts = 0
  }

  /** Stop all synchronisation permanently. No more API requests after this. */
  stop() {
    this._stopped = true
    this._hidden = false
    this._cleanupAll()
  }

  /** Page hidden — suspend WS, reconnect timer, and polling. */
  onHide() {
    this._hidden = true
    this._cleanupTransient()
  }

  /** Page shown — resume synchronisation. */
  onShow() {
    if (this._stopped) return
    this._hidden = false
    this._reconnectAttempts = 0
    if (this._allTerminal()) return

    // Run calibration immediately on return from background
    this._calibrateOnce()

    // Reconnect if everything was cleaned up
    if (!this._wsOpened) {
      this._connectWebSocket()
    }
  }

  /** Page unloaded — permanent cleanup. Same as stop(). */
  onUnload() {
    this.stop()
  }

  /** Check if all tracked tasks are in a terminal state. */
  allTerminal() {
    return this._allTerminal()
  }

  // ── Internal: lifecycle helpers ──

  _cleanupTransient() {
    this._closeWebSocket()
    this._clearTimers()
    this._wsOpened = false
  }

  _cleanupAll() {
    this._cleanupTransient()
    this._taskIds.clear()
    this._taskStatuses = {}
  }

  _allTerminal() {
    // Empty set means all tasks have been removed (terminal)
    return this._taskIds.size === 0
  }

  // ── Transition protection ──

  /**
   * Returns true if the update should be accepted.
   * Rejects updates that would regress a terminal state to a non-terminal one.
   */
  _acceptTransition(taskId, newStatus) {
    const current = this._taskStatuses[taskId]
    if (!current) return true  // no known state → accept

    const currentRank = STATE_RANK[current] !== undefined ? STATE_RANK[current] : -1
    const newRank = STATE_RANK[newStatus] !== undefined ? STATE_RANK[newStatus] : -1

    // Never allow terminal → non-terminal
    if (currentRank === 2 && newRank < 2) return false
    // Never allow completed → failed (or vice versa)
    if (currentRank === 2 && newRank === 2 && current !== newStatus) return false
    // Allow same state or forward progression
    return true
  }

  // ── WebSocket ──

  _connectWebSocket() {
    // Feature flag: config may disable WS entirely
    const wsEnabled = config.EXPORT_WS_ENABLED
    if (wsEnabled === false) {
      this._startPolling()
      return
    }

    if (this._stopped || this._hidden) return
    if (this._wsOpened) return

    // Exceeded reconnect limit — fall back to polling permanently
    if (this._reconnectAttempts >= this._maxReconnectAttempts) {
      this._startPolling()
      return
    }

    // Clean up any previous connection state
    this._closeWebSocket()
    this._clearTimers()

    const token = storage.get('token')
    if (!token) {
      this._startPolling()
      return
    }

    const wsBase = config.BASE_URL.replace(/^http/, 'ws').replace(/\/api\/v1$/, '')
    const wsUrl = `${wsBase}/api/v1/exports/ws?token=${encodeURIComponent(token || '')}`

    try {
      const socketTask = wx.connectSocket({
        url: wsUrl,
        header: {
          'X-Trace-ID': this._traceId,
          'X-Request-ID': api.createRequestId(),
        },
        fail: () => this._fallbackToPolling(),
      })
      this._ws = socketTask

      socketTask.onOpen(() => {
        if (this._stopped) {
          this._closeWebSocket()
          return
        }
        this._wsOpened = true
        this._consecutiveErrors = 0
        this._reconnectAttempts = 0

        // If we were polling, stop — WS is healthy now
        this._stopPolling()

        // Start heartbeat pings
        this._startHeartbeat()

        // Start calibration polling (reduced frequency, always on)
        this._startCalibration()

        // Send initial ping to verify
        this._wsSend({ type: 'ping' })
      })

      socketTask.onMessage((res) => {
        if (this._stopped) return
        try {
          const msg = JSON.parse(res.data)
          this._handleMessage(msg)
        } catch (e) {
          // Malformed message — ignore
        }
      })

      socketTask.onError(() => {
        if (this._stopped) return
        this._wsOpened = false
        this._fallbackToPolling()
      })

      socketTask.onClose(() => {
        this._wsOpened = false
        this._stopHeartbeat()
        if (this._stopped || this._hidden) return
        // Schedule reconnect
        this._scheduleReconnect()
      })
    } catch (e) {
      this._fallbackToPolling()
    }
  }

  /** Route incoming WS messages by task_id. */
  _handleMessage(msg) {
    if (msg.type === 'pong') {
      // Server responded to our ping — connection alive
      return
    }
    if (msg.type === 'ping') {
      // Server heartbeat — respond
      this._wsSend({ type: 'pong' })
      return
    }
    if (msg.type === 'export_status' && msg.task_id) {
      const tid = Number(msg.task_id)
      if (this._taskIds.has(tid)) {
        const newStatus = msg.status
        if (!this._acceptTransition(tid, newStatus)) {
          return  // reject stale/non-forward update
        }
        this._taskStatuses[tid] = newStatus
        if (this._onUpdate) this._onUpdate(tid, msg)

        // Remove terminal tasks from tracking
        if (TERMINAL_STATES.includes(newStatus)) {
          this._taskIds.delete(tid)
          if (this._allTerminal()) {
            this.pause()
          }
        }
      }
      return
    }
  }

  _wsSend(data) {
    try {
      if (this._ws && this._wsOpened) {
        this._ws.send({
          data: JSON.stringify(data),
          fail: () => {
            this._wsOpened = false
            this._fallbackToPolling()
          },
        })
      }
    } catch (e) {
      // Ignore send errors
    }
  }

  _closeWebSocket() {
    if (this._ws) {
      try { this._ws.close() } catch (e) { /* ignore */ }
      this._ws = null
    }
    this._wsOpened = false
  }

  _startHeartbeat() {
    this._stopHeartbeat()
    this._heartbeatTimer = setInterval(() => {
      if (this._stopped || !this._wsOpened) {
        this._stopHeartbeat()
        return
      }
      this._wsSend({ type: 'ping' })
    }, WS_HEARTBEAT_INTERVAL)
  }

  _stopHeartbeat() {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer)
      this._heartbeatTimer = null
    }
  }

  // ── Reconnect ──

  _scheduleReconnect() {
    if (this._reconnectTimer) return
    this._reconnectAttempts++
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null
      if (!this._stopped && !this._hidden && !this._wsOpened) {
        this._connectWebSocket()
      }
    }, 5000)
  }

  // ── Calibration polling (always on when tasks are non-terminal) ──
  //
  // Even when WebSocket is healthy, we periodically re-fetch from the database
  // to recover from missed events (cross-process loss, backend restart, etc.).
  // When WS is down, this becomes the primary sync mechanism at a faster rate.

  _startCalibration() {
    this._stopCalibration()
    if (this._allTerminal()) return

    const calibrate = async () => {
      if (this._stopped || this._hidden || this._allTerminal()) return

      // Wait for the current calibration to finish before scheduling another.
      // The previous fire-and-forget loop could stack GET requests indefinitely
      // on a slow network, making the records page appear frozen.
      await this._calibrateOnce()

      if (!this._stopped && !this._hidden && !this._allTerminal() && this._wsOpened) {
        this._pollTimer = setTimeout(calibrate, CALIBRATION_INTERVAL_WS)
      }
    }

    // Start first calibration after a short delay (allow WS events to settle first)
    this._pollTimer = setTimeout(calibrate, 1500)
  }

  _stopCalibration() {
    if (this._pollTimer) {
      clearTimeout(this._pollTimer)
      this._pollTimer = null
    }
  }

  /** Fetch latest task status from DB for all tracked non-terminal tasks. */
  async _calibrateOnce() {
    if (this._stopped || this._allTerminal()) return
    if (this._calibrationPromise) return this._calibrationPromise

    this._calibrationPromise = this._runCalibrationOnce()
    try {
      return await this._calibrationPromise
    } finally {
      this._calibrationPromise = null
    }
  }

  async _runCalibrationOnce() {
    // Collect IDs from tasks that are not known to be terminal
    const ids = Array.from(this._taskIds)

    for (let taskIndex = 0; taskIndex < ids.length; taskIndex++) {
      const tid = ids[taskIndex]
      if (this._stopped || this._hidden || this._allTerminal()) return
      try {
        const task = await api.get(`/exports/${tid}`, { _traceId: this._traceId })
        this._consecutiveErrors = 0

        // Transition protection: don't regress terminal state
        if (!this._acceptTransition(tid, task.status)) {
          continue
        }

        this._taskStatuses[tid] = task.status
        if (this._onUpdate) this._onUpdate(tid, task)

        if (TERMINAL_STATES.includes(task.status)) {
          this._taskIds.delete(tid)
        }
      } catch (e) {
        this._consecutiveErrors++
        if (this._onError && this._consecutiveErrors <= 3) {
          this._onError(e)
        }
      }
    }

    if (this._allTerminal()) {
      this.pause()
    }
  }

  // ── Fallback polling (single loop, used only when WS unavailable) ──
  //
  // When the WebSocket is down, we use this as the primary sync mechanism.
  // When WS comes back, this stops and calibration takes over.

  _fallbackToPolling() {
    if (this._stopped || this._hidden) return
    this._closeWebSocket()
    this._stopHeartbeat()
    this._startPolling()
  }

  _startPolling() {
    if (this._pollTimer) return  // Already polling — single loop guarantee
    if (this._taskIds.size === 0) return

    const poll = async () => {
      if (this._stopped) return

      // If WS reconnected while we were waiting, switch to calibration mode
      if (this._wsOpened) {
        this._stopPolling()
        this._startCalibration()
        return
      }

      try {
        const ids = Array.from(this._taskIds)
        for (let taskIndex = 0; taskIndex < ids.length; taskIndex++) {
          const tid = ids[taskIndex]
          if (this._stopped) return
          try {
            const task = await api.get(`/exports/${tid}`, { _traceId: this._traceId })
            this._consecutiveErrors = 0

            // Transition protection
            if (!this._acceptTransition(tid, task.status)) {
              continue
            }

            this._taskStatuses[tid] = task.status
            if (this._onUpdate) this._onUpdate(tid, task)

            if (TERMINAL_STATES.includes(task.status)) {
              this._taskIds.delete(tid)
            }
          } catch (e) {
            this._consecutiveErrors++
            if (this._onError) this._onError(e)
          }
        }

        if (this._allTerminal()) {
          this.pause()
          return
        }
      } catch (e) {
        this._consecutiveErrors++
        if (this._consecutiveErrors >= this._maxConsecutiveErrors) {
          this._stopPolling()
          if (this._onError) this._onError(new Error('连续轮询失败'))
          return
        }
      }

      // Schedule next poll
      if (!this._stopped) {
        const backoff = this._consecutiveErrors > 0
          ? this._pollIntervalMs * 2
          : this._pollIntervalMs
        this._pollTimer = setTimeout(poll, backoff)
      }
    }

    // Start first poll after a short delay
    this._pollTimer = setTimeout(poll, 500)
  }

  _stopPolling() {
    if (this._pollTimer) {
      clearTimeout(this._pollTimer)
      this._pollTimer = null
    }
  }

  _clearTimers() {
    this._stopPolling()  // covers both polling and calibration timers
    this._stopHeartbeat()
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }
  }
}

/**
 * Convenience — create a manager, add tasks, start, and return the manager.
 *
 * @param {number|number[]} taskIds - One or more task IDs to track
 * @param {object} options - Same as ExportStatusSyncManager constructor
 * @returns {ExportStatusSyncManager}
 */
function syncExportTasks(taskIds, options = {}) {
  const mgr = new ExportStatusSyncManager(options)
  const ids = Array.isArray(taskIds) ? taskIds : [taskIds]
  ids.forEach(id => mgr.addTask(id))
  mgr.start()
  return mgr
}

module.exports = {
  ExportStatusSyncManager,
  syncExportTasks,
}

/**
 * ExportStatusSyncManager — page-level WebSocket+fallback polling for export tasks.
 *
 * Design:
 * - One WebSocket per page instance (not per task).
 * - Routes incoming status events by task_id to registered callbacks.
 * - No backup polling while the WebSocket is healthy.
 * - A single fallback polling loop starts only when WebSocket fails.
 * - Properly manages lifecycle: hide/show/unload/stop.
 *
 * Usage:
 *   const sync = new ExportStatusSyncManager({
 *     onUpdate: (taskId, taskData) => { ... },
 *     onError: (err) => { ... },
 *   })
 *   sync.addTask(42)
 *   sync.addTask(43)
 *   sync.start()
 *   // ... page onHide:
 *   sync.onHide()
 *   // ... page onShow:
 *   sync.onShow()
 *   // ... done:
 *   sync.stop()
 */
const api = require('../utils/api')
const config = require('../config')
const storage = require('../utils/storage')

const TERMINAL_STATES = ['completed', 'failed', 'expired']
const WS_HEARTBEAT_INTERVAL = 25000

class ExportStatusSyncManager {
  /**
   * @param {object} options
   * @param {function(number, object)} [options.onUpdate] - Called with (taskId, data) on status change
   * @param {function(Error)} [options.onError] - Called on non-fatal errors
   * @param {number} [options.pollIntervalMs=3000] - Polling interval in ms
   */
  constructor(options = {}) {
    this._taskIds = new Set()
    this._onUpdate = options.onUpdate || null
    this._onError = options.onError || null
    this._pollIntervalMs = options.pollIntervalMs || 3000

    // Internal state
    this._stopped = false
    this._ws = null
    this._wsHealthy = false
    this._pollTimer = null
    this._reconnectTimer = null
    this._heartbeatTimer = null
    this._consecutiveErrors = 0
    this._maxConsecutiveErrors = 5
    this._hidden = false
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
  }

  /** Replace all tracked task IDs. */
  setTaskIds(ids) {
    this._taskIds = new Set(ids.filter(id => typeof id === 'number'))
  }

  /** Start or resume synchronisation. Safe to call multiple times. */
  start() {
    if (this._stopped) return
    this._hidden = false

    // Only connect if there are tasks to monitor
    if (this._taskIds.size === 0) return

    // Don't reconnect if WS is already healthy
    if (this._wsHealthy) return

    this._connectWebSocket()
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
    if (this._allTerminal()) return

    // Reconnect if everything was cleaned up
    this._connectWebSocket()
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
    this._wsHealthy = false
  }

  _cleanupAll() {
    this._cleanupTransient()
    this._taskIds.clear()
  }

  _allTerminal() {
    // We don't track per-task terminal state internally.
    // The caller is responsible for calling removeTask() when
    // they receive a terminal update via onUpdate.
    // When the set is empty, everything is terminal.
    return this._taskIds.size === 0
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
    if (this._wsHealthy) return

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
      this._ws = wx.connectSocket({ url: wsUrl, fail: () => this._fallbackToPolling() })

      this._ws.onOpen(() => {
        if (this._stopped) {
          this._closeWebSocket()
          return
        }
        this._wsHealthy = true
        this._consecutiveErrors = 0

        // If we were polling, stop — WS is healthy now
        this._stopPolling()

        // Start heartbeat pings
        this._startHeartbeat()

        // Send initial ping to verify
        this._wsSend({ type: 'ping' })
      })

      this._ws.onMessage((res) => {
        if (this._stopped) return
        try {
          const msg = JSON.parse(res.data)
          this._handleMessage(msg)
        } catch (e) {
          // Malformed message — ignore
        }
      })

      this._ws.onError(() => {
        if (this._stopped) return
        this._wsHealthy = false
        this._fallbackToPolling()
      })

      this._ws.onClose(() => {
        this._wsHealthy = false
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
        if (this._onUpdate) this._onUpdate(tid, msg)

        // Remove terminal tasks from tracking
        if (TERMINAL_STATES.includes(msg.status)) {
          this._taskIds.delete(tid)
          if (this._allTerminal()) {
            this.stop()
          }
        }
      }
      return
    }
  }

  _wsSend(data) {
    try {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        this._ws.send({ data: JSON.stringify(data) })
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
    this._wsHealthy = false
  }

  _startHeartbeat() {
    this._stopHeartbeat()
    this._heartbeatTimer = setInterval(() => {
      if (this._stopped || !this._wsHealthy) {
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
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null
      if (!this._stopped && !this._hidden && !this._wsHealthy) {
        this._connectWebSocket()
      }
    }, 5000)
  }

  // ── Fallback polling (single loop) ──

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

      // If WS reconnected while we were waiting, stop polling
      if (this._wsHealthy) {
        this._stopPolling()
        return
      }

      try {
        // Poll each tracked task individually
        const ids = Array.from(this._taskIds)
        for (const tid of ids) {
          if (this._stopped) return
          try {
            const task = await api.get(`/exports/${tid}`)
            this._consecutiveErrors = 0
            if (this._onUpdate) this._onUpdate(tid, task)

            if (TERMINAL_STATES.includes(task.status)) {
              this._taskIds.delete(tid)
            }
          } catch (e) {
            // Individual task error — report via onError
            this._consecutiveErrors++
            if (this._onError) this._onError(e)
          }
        }

        if (this._allTerminal()) {
          this.stop()
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
    this._stopPolling()
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

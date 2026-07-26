/**
 * Export API service — wraps export-related API calls and polling.
 */
const api = require('../utils/api')

/**
 * Preview export count for a given range + filters.
 */
function previewCount(params) {
  return api.post('/exports/preview-count', params)
}

/**
 * Create a new export task.
 */
function createExport(params) {
  return api.post('/exports', params)
}

/**
 * List export records for the current user.
 */
function listExports(page = 1, pageSize = 20) {
  return api.get('/exports', { page, page_size: pageSize })
}

/**
 * Get a single export task's details.
 */
function getExport(taskId) {
  return api.get(`/exports/${taskId}`)
}

/**
 * Get download info for a completed export.
 */
function getDownloadInfo(taskId) {
  return api.get(`/exports/${taskId}/download`)
}

/**
 * Get the file stream URL for local-storage exports.
 */
function getFileUrl(taskId) {
  const config = require('../config')
  return `${config.apiBase}/exports/${taskId}/file`
}

/**
 * Delete an export task.
 */
function deleteExport(taskId) {
  return api.del(`/exports/${taskId}`)
}

/**
 * Retry a failed export task.
 */
function retryExport(taskId) {
  return api.post(`/exports/${taskId}/retry`)
}

/**
 * Re-export using the original snapshot and config.
 */
function reExport(taskId) {
  return api.post(`/exports/${taskId}/re-export`)
}

/**
 * Start polling a task until it reaches a terminal state.
 * Returns a stop function.
 */
function pollTaskStatus(taskId, onUpdate, onError, intervalMs = 2500) {
  let timer = null
  let stopped = false
  let consecutiveErrors = 0
  const MAX_CONSECUTIVE_ERRORS = 5

  async function poll() {
    if (stopped) return

    try {
      const res = await getExport(taskId)
      consecutiveErrors = 0
      const task = res

      if (onUpdate) onUpdate(task)

      const terminalStates = ['completed', 'failed', 'expired']
      if (!terminalStates.includes(task.status)) {
        if (!stopped) timer = setTimeout(poll, intervalMs)
      }
    } catch (err) {
      consecutiveErrors++
      if (onError) onError(err)
      if (consecutiveErrors < MAX_CONSECUTIVE_ERRORS && !stopped) {
        timer = setTimeout(poll, intervalMs * 2)
      }
    }
  }

  // Start polling
  timer = setTimeout(poll, 500)

  return function stop() {
    stopped = true
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }
}

/**
 * Start WebSocket connection for real-time export task status.
 * Falls back to polling if WebSocket fails.
 *
 * @param {number} taskId - Task ID to subscribe to
 * @param {function} onUpdate - Callback with updated task data
 * @param {function} onError - Error callback
 * @param {object} options - { pollIntervalMs: 3000 }
 * @returns {function} stop function
 */
function syncTaskStatus(taskId, onUpdate, onError, options = {}) {
  const pollInterval = options.pollIntervalMs || 3000
  let stopped = false
  let ws = null
  let pollTimer = null
  let reconnectTimer = null
  let usePolling = false

  const config = require('../config')
  const storage = require('../utils/storage')
  const token = storage.get('token')

  // ── WebSocket approach ──
  function connectWebSocket() {
    if (stopped || usePolling) return

    // Determine WebSocket URL from API base
    const apiBase = config.apiBase || config.BASE_URL || ''
    const wsBase = apiBase.replace(/^http/, 'ws').replace(/\/api\/v1$/, '')
    const wsUrl = `${wsBase}/api/v1/exports/ws?token=${encodeURIComponent(token || '')}`

    try {
      ws = wx.connectSocket({ url: wsUrl, fail: () => fallbackToPolling() })

      ws.onOpen(() => {
        // Connected — send ping to verify
        ws.send({ data: JSON.stringify({ type: 'ping' }) })
      })

      ws.onMessage((res) => {
        try {
          const msg = JSON.parse(res.data)
          if (msg.type === 'export_status') {
            if (!msg.task_id || (taskId && msg.task_id !== taskId)) return
            if (onUpdate) onUpdate(msg)
          } else if (msg.type === 'pong') {
            // Connection alive
          } else if (msg.type === 'ping') {
            // Server heartbeat — respond
            ws.send({ data: JSON.stringify({ type: 'ping' }) })
          }
        } catch (e) {
          // ignore parse errors
        }
      })

      ws.onError(() => {
        if (!usePolling) fallbackToPolling()
      })

      ws.onClose(() => {
        if (!stopped && !usePolling) {
          // Try reconnect once
          reconnectTimer = setTimeout(() => {
            if (!stopped) connectWebSocket()
          }, 5000)
        }
      })
    } catch (e) {
      fallbackToPolling()
    }
  }

  // ── Polling fallback ──
  function fallbackToPolling() {
    if (usePolling || stopped) return
    usePolling = true
    if (ws) { ws.close(); ws = null }

    pollTaskStatus(taskId, onUpdate, onError, pollInterval)
    // pollTaskStatus returns a stop function, store it differently
  }

  // Start
  if (token) {
    connectWebSocket()
  } else {
    fallbackToPolling()
  }

  // Also start polling as backup in case WebSocket messages are missed
  // This ensures we get terminal state even if WS drops
  const backupPollTimer = setTimeout(() => {
    if (!stopped) {
      _startBackupPoll(taskId, onUpdate, onError, pollInterval)
    }
  }, 15000) // Start backup polling after 15 seconds

  function _startBackupPoll(tid, onUpd, onErr, interval) {
    if (stopped) return
    let consecutiveErrors = 0
    const MAX_CONSECUTIVE_ERRORS = 5

    async function poll() {
      if (stopped) return
      try {
        const res = await getExport(tid)
        consecutiveErrors = 0
        if (onUpd) onUpd(res)

        const terminalStates = ['completed', 'failed', 'expired']
        if (!terminalStates.includes(res.status) && !stopped) {
          pollTimer = setTimeout(poll, interval)
        }
      } catch (err) {
        consecutiveErrors++
        if (onErr) onErr(err)
        if (consecutiveErrors < MAX_CONSECUTIVE_ERRORS && !stopped) {
          pollTimer = setTimeout(poll, interval * 2)
        }
      }
    }

    pollTimer = setTimeout(poll, 500)
  }

  return function stop() {
    stopped = true
    if (ws) { ws.close(); ws = null }
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (backupPollTimer) { clearTimeout(backupPollTimer) }
  }
}

module.exports = {
  previewCount,
  createExport,
  listExports,
  getExport,
  getDownloadInfo,
  getFileUrl,
  deleteExport,
  retryExport,
  reExport,
  pollTaskStatus,
  syncTaskStatus,
}

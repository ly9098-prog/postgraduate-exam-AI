/**
 * Export API service — wraps export-related API calls and polling.
 */
const api = require('../utils/api')

/**
 * Get user export capabilities (feature flags + whitelist check).
 */
function getCapabilities() {
  return api.get('/exports/capabilities')
}

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
  return config.BASE_URL + '/exports/' + taskId + '/file'
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
 * DEPRECATED: Use ExportStatusSyncManager from export_status_sync.js instead.
 * This wrapper delegates to ExportStatusSyncManager for backward compatibility.
 *
 * @param {number} taskId - Task ID to subscribe to
 * @param {function} onUpdate - Callback with updated task data
 * @param {function} onError - Error callback
 * @param {object} options - { pollIntervalMs: 3000 }
 * @returns {function} stop function
 */
function syncTaskStatus(taskId, onUpdate, onError, options = {}) {
  const { ExportStatusSyncManager } = require('./export_status_sync')
  const mgr = new ExportStatusSyncManager({
    onUpdate: (tid, data) => {
      if (tid !== taskId || !onUpdate) return
      // Normalize data shape: WS events use task_id, polling uses id
      const normalized = { ...data }
      if (normalized.task_id !== undefined && normalized.id === undefined) {
        normalized.id = normalized.task_id
      }
      onUpdate(normalized)
    },
    onError,
    pollIntervalMs: options.pollIntervalMs || 3000,
  })
  mgr.addTask(taskId)
  mgr.start()

  return function stop() {
    mgr.stop()
  }
}

/**
 * Get a user-facing error message for capability check failures.
 *
 * @param {Error|null} error - The ApiError or raw error object, or null if capability response was received.
 * @param {object|null} capability - The capability response (if received).
 * @returns {string} User-facing error message.
 */
function getExportCapabilityErrorMessage(error, capability) {
  // Capability response with reason_code
  if (capability) {
    if (capability.reason_code === 'feature_disabled') {
      return '导出功能当前已关闭'
    }
    if (capability.reason_code === 'user_not_allowed') {
      return '当前账号暂未获得导出权限'
    }
    // Unknown reason_code — fall through
  }

  // Network or API error
  if (error) {
    if (error.code === 'NETWORK_ERROR' || error.code === 'AUTH_REQUIRED') {
      return '无法连接导出服务，请检查网络和小程序环境配置'
    }
    // 优先使用服务端返回的消息
    if (error.message && !error.message.includes('请求失败')) {
      return error.message
    }
  }

  return '获取导出能力失败，请稍后重试'
}

module.exports = {
  getCapabilities,
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
  getExportCapabilityErrorMessage,
}

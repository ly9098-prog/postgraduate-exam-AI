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
}

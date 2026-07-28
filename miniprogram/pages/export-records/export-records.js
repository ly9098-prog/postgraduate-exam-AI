/**
 * Export records page — list, sync, preview, share, delete, retry, re-export.
 *
 * Architecture:
 * - Single ``ExportStatusSyncManager`` per page instance (not one per task).
 * - WebSocket for real-time events + calibration polling from DB (always on).
 * - Task enrichment recomputed after every update.
 * - Completion toast shown only once per task via ``_completedNotified`` set.
 */
const exportApi = require('../../services/export')
const { ExportStatusSyncManager } = require('../../services/export_status_sync')
const previewTempFiles = require('../../utils/preview-temp-files')

const STATUS_MAP = {
  pending: {
    label: '等待处理',
    summary: '任务已进入导出队列',
    tone: 'neutral',
    glyph: '···',
    terminal: false,
  },
  processing: {
    label: '正在导出',
    summary: '正在生成文件，请稍候',
    tone: 'info',
    glyph: '',
    terminal: false,
  },
  completed: {
    label: '导出完成',
    summary: '文件已准备好',
    tone: 'success',
    glyph: '✓',
    terminal: true,
  },
  failed: {
    label: '导出失败',
    summary: '本次导出未完成',
    tone: 'danger',
    glyph: '!',
    terminal: true,
  },
  expired: {
    label: '文件已过期',
    summary: '文件已超过保存期限',
    tone: 'muted',
    glyph: '—',
    terminal: true,
  },
}

const FORMAT_MAP = {
  pdf: 'PDF',
  docx: 'Word',
}

const TERMINAL_STATES = ['completed', 'failed', 'expired']
const PENDING_WARNING_SECONDS = 30
const PROCESSING_WARNING_SECONDS = 300  // 5 minutes

function pad2(value) {
  return Number(value) < 10 ? '0' + Number(value) : String(value)
}

/**
 * Parse API timestamps consistently on iOS and Android.
 * Timestamps without a timezone are treated as local time, matching the
 * existing page behaviour while avoiding iOS Date parsing differences.
 */
function parseDateValue(value) {
  if (!value) return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }

  const raw = String(value).trim()
  if (!raw) return null

  let normalized = raw
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  if (!hasTimezone) {
    normalized = raw
      .replace(/-/g, '/')
      .replace('T', ' ')
      .replace(/\.\d+$/, '')
  }

  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

function formatDateTime(value) {
  const date = parseDateValue(value)
  if (!date) return value ? String(value) : ''

  return [
    date.getFullYear() + '年',
    date.getMonth() + 1 + '月',
    date.getDate() + '日 ',
    pad2(date.getHours()) + ':' + pad2(date.getMinutes()),
  ].join('')
}

function formatExpiry(value, status) {
  const date = parseDateValue(value)
  if (!date) {
    return {
      expiresText: value ? '有效期至 ' + String(value) : '',
      expiresRelativeText: status === 'expired' ? '已到期' : '',
      expiresSoon: false,
    }
  }

  const now = Date.now()
  const diffMs = date.getTime() - now
  const absHours = Math.ceil(Math.abs(diffMs) / (60 * 60 * 1000))
  const days = Math.ceil(diffMs / (24 * 60 * 60 * 1000))
  let relative = ''

  if (status === 'expired' || diffMs <= 0) {
    relative = '已到期'
  } else if (diffMs < 60 * 60 * 1000) {
    relative = '不足 1 小时到期'
  } else if (diffMs < 24 * 60 * 60 * 1000) {
    relative = absHours + ' 小时后到期'
  } else {
    relative = '剩余 ' + days + ' 天'
  }

  return {
    expiresText: '有效期至 ' + (date.getMonth() + 1) + '月' + date.getDate() + '日 ' +
      pad2(date.getHours()) + ':' + pad2(date.getMinutes()),
    expiresRelativeText: relative,
    expiresSoon: diffMs > 0 && diffMs <= 24 * 60 * 60 * 1000,
  }
}

function formatFileSize(bytes) {
  const size = Number(bytes)
  if (!size || size < 0) return ''
  if (size < 1024) return size + ' B'
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB'
  return (size / (1024 * 1024)).toFixed(1) + ' MB'
}

Page({
  data: {
    list: [],
    page: 1,
    hasMore: false,
    loading: false,
    highlightId: null,
    expandedActionId: null,
    previewingTaskId: null,
    reExportingTaskId: null,
    skeletonItems: [1, 2],

    // Custom dialog
    dialogVisible: false,
    dialogTitle: '',
    dialogContent: '',
    dialogConfirmText: '确定',
    dialogCancelText: '取消',
    dialogShowCancel: true,
    dialogTone: 'default',
  },

  /**
   * Non-reactive instance fields (not in data — not sent to WXML).
   */
  _pageAlive: false,
  _statusSyncManager: null,
  _hasLoadedOnce: false,
  _loadPromise: null,
  _completedNotified: null,
  _taskWatchStartedAt: null,  // Map<taskId, timestamp> for timeout detection
  _watchTimer: null,  // periodic check for long-running tasks
  _dialogResolver: null,
  _previewFileCache: null,
  _previewDownloadPromises: null,
  _suppressNextShowRefresh: false,
  _pageDestroyed: false,

  onLoad(options) {
    this._pageDestroyed = false
    this._pageAlive = true
    this._completedNotified = new Set()
    this._taskWatchStartedAt = new Map()
    this._previewFileCache = new Map()
    this._previewDownloadPromises = new Map()
    this._suppressNextShowRefresh = false
    this._startWatchTimer()

    if (options.highlight) {
      this.setData({ highlightId: parseInt(options.highlight, 10) })
    }

    // Create a single status sync manager for this page
    this._createSyncManager()

    // Load list (first call — both onLoad and onShow will run, dedup via _hasLoadedOnce)
    this._loadList(true)
  },

  onShow() {
    this._pageAlive = true

    // wx.openDocument hides the page while the document viewer is active.
    // Always clear the transient button state when the page becomes visible
    // again, including after re-exporting or returning from a failed open.
    if (this.data.previewingTaskId !== null) {
      this.setData({ previewingTaskId: null })
    }
    this._startWatchTimer()

    if (this._hasLoadedOnce) {
      // Opening WeChat's share panel briefly hides/shows the page. Skip the
      // single resulting refresh so scroll position and card layout stay put.
      if (this._suppressNextShowRefresh) {
        this._suppressNextShowRefresh = false
      } else {
        this._loadList(true)
      }
    }

    // Restart status sync if stopped or hidden
    if (this._statusSyncManager) {
      this._statusSyncManager.onShow()
    } else {
      this._createSyncManager()
    }
  },

  onHide() {
    this._pageAlive = false
    this._stopWatchTimer()
    if (this._statusSyncManager) {
      this._statusSyncManager.onHide()
    }
  },

  onUnload() {
    this._pageDestroyed = true
    this._pageAlive = false
    this._stopWatchTimer()
    this._destroySyncManager()
    if (this._completedNotified) this._completedNotified.clear()
    if (this._taskWatchStartedAt) {
      this._taskWatchStartedAt.clear()
    }
    if (this._previewFileCache) this._previewFileCache.clear()
    if (this._previewDownloadPromises) this._previewDownloadPromises.clear()
    if (this._dialogResolver) {
      this._dialogResolver({ confirm: false, cancel: true })
      this._dialogResolver = null
    }
  },

  // ── Single status sync manager ──

  _createSyncManager() {
    if (this._statusSyncManager) return

    this._statusSyncManager = new ExportStatusSyncManager({
      onUpdate: (taskId, data) => this._onStatusUpdate(taskId, data),
      onError: () => {
        // Non-fatal — sync service handles internally
      },
    })
  },

  _destroySyncManager() {
    if (this._statusSyncManager) {
      this._statusSyncManager.stop()
      this._statusSyncManager = null
    }
  },

  /**
   * Rebuild tracked task IDs from current list and push to sync manager.
   */
  _restartStatusSync() {
    if (!this._statusSyncManager) return
    if (!this._pageAlive) return

    const taskIds = this.data.list
      .filter(item => !TERMINAL_STATES.includes(item.status))
      .map(item => Number(item.id))

    this._statusSyncManager.setTaskIds(taskIds)
    if (taskIds.length > 0) {
      this._statusSyncManager.start()
    } else {
      // No active tasks right now. Keep the manager reusable so a newly
      // created retry/re-export task can start synchronising immediately.
      this._statusSyncManager.pause()
    }
  },

  // ── Status update handler ──

  /**
   * Called by sync manager during calibration — updates individual task states.
   */
  async _onStatusUpdate(taskId, data) {
    if (!this._pageAlive) return

    // Normalize: WS events use task_id, API responses use id
    const normalized = this._normalizeUpdate(taskId, data)

    // Check if this is a transition INTO completed
    const oldTask = this.data.list.find(t => t.id === taskId)
    const wasCompleted = oldTask && TERMINAL_STATES.includes(oldTask.status)
    const isNowCompleted = TERMINAL_STATES.includes(normalized.status)

    if (isNowCompleted && !wasCompleted && normalized.status === 'completed') {
      // Load full task details for completed tasks (WS events are partial)
      try {
        const full = await exportApi.getExport(taskId)
        Object.assign(normalized, full)
      } catch (e) {
        // Use what we have
      }
    }

    // Enrich and merge
    const enriched = this._enrichTask(normalized)
    this._mergeTask(enriched)

    // Show completion toast once per task
    if (isNowCompleted && !wasCompleted && normalized.status === 'completed') {
      if (!this._completedNotified.has(taskId)) {
        this._completedNotified.add(taskId)
        wx.showToast({ title: '导出完成', icon: 'success' })
      }
    }
  },

  /**
   * Normalize a status update to a consistent shape.
   */
  _normalizeUpdate(taskId, data) {
    const base = { id: taskId }
    // WS events use task_id/status; API responses use id/status
    if (data.task_id !== undefined && data.id === undefined) {
      base.id = Number(data.task_id)
    }
    return { ...base, ...data, id: taskId }
  },

  /**
   * Merge a single task update into the list. Preserves fields the update
   * doesn't carry (WS events are partial).
   */
  _mergeTask(updated) {
    const list = this.data.list.map(t => {
      if (t.id !== updated.id) return t
      const merged = { ...t, ...updated }
      if (this._previewCacheVersion(t) !== this._previewCacheVersion(merged)) {
        this._invalidatePreviewCache(t.id)
      }
      // Re-enrich the complete merged task so partial WebSocket events do not
      // overwrite formatted fields with empty fallback values.
      return this._enrichTask(merged)
    })
    this.setData({ list })
  },

  /**
   * Insert or replace a task at the top of the list. This remains useful for
   * newly-created tasks received before the next list refresh.
   */
  _upsertTaskAtTop(task) {
    const taskId = Number(task && task.id)
    if (!taskId) return

    const enriched = this._enrichTask({ ...task, id: taskId })
    const list = [enriched].concat(
      this.data.list.filter(item => Number(item.id) !== taskId)
    )
    this.setData({
      list,
      highlightId: taskId,
      expandedActionId: null,
    })
    this._restartStatusSync()
  },

  // ── List loading ──

  async _loadList(reset = false) {
    if (!this._pageAlive) return
    if (this.data.loading) return

    // Dedup concurrent loads
    if (this._loadPromise) {
      return this._loadPromise
    }

    this.setData({ loading: true })

    const page = reset ? 1 : this.data.page + 1
    const loadFn = async () => {
      try {
        const res = await exportApi.listExports(page, 20)
        const tasks = res.items || []
        const enriched = tasks.map(t => this._enrichTask(t))
        const list = reset ? enriched : [...this.data.list, ...enriched]

        this.setData({
          list,
          page: res.page || page,
          hasMore: tasks.length === 20,
          loading: false,
        })

        this._hasLoadedOnce = true

        // Rebuild sync manager task set
        this._restartStatusSync()
      } catch (err) {
        this.setData({ loading: false })
        if (this._pageAlive) {
          wx.showToast({ title: '加载失败', icon: 'none' })
        }
      }
    }

    this._loadPromise = loadFn()
    try {
      return await this._loadPromise
    } finally {
      this._loadPromise = null
    }
  },

  /**
   * Periodic watch timer — checks task durations and updates warnings.
   * Runs every 10 seconds while page is alive.
   */
  _startWatchTimer() {
    this._stopWatchTimer()
    this._watchTimer = setInterval(() => {
      if (!this._pageAlive) {
        this._stopWatchTimer()
        return
      }
      this._checkTaskDurations()
    }, 10000)
  },

  _stopWatchTimer() {
    if (this._watchTimer) {
      clearInterval(this._watchTimer)
      this._watchTimer = null
    }
  },

  /**
   * Check non-terminal task durations and update enriched fields.
   * Called periodically by _startWatchTimer and after each status update.
   */
  _checkTaskDurations() {
    if (!this._pageAlive) return
    if (!this._taskWatchStartedAt) return
    if (this.data.list.length === 0) return

    const now = Date.now()
    var needsUpdate = false
    const list = this.data.list.map(t => {
      let nextTask = t

      // Keep the human-readable expiry countdown fresh while the page stays open.
      if (t.expires_at) {
        const expiry = formatExpiry(t.expires_at, t.status)
        if (
          expiry.expiresText !== t.expiresText ||
          expiry.expiresRelativeText !== t.expiresRelativeText ||
          expiry.expiresSoon !== t.expiresSoon
        ) {
          needsUpdate = true
          nextTask = { ...nextTask, ...expiry }
        }
      }

      // Only check timeout warnings for non-terminal tasks that we're watching.
      if (TERMINAL_STATES.includes(t.status)) return nextTask
      const watchStart = this._taskWatchStartedAt.get(t.id)
      if (!watchStart) return nextTask

      const elapsed = (now - watchStart) / 1000
      var warning = null

      if (t.status === 'pending') {
        if (elapsed > PENDING_WARNING_SECONDS) {
          if (t.status_reason === 'processor_unavailable') {
            warning = '导出处理服务可能未启动，请稍后重试'
          } else {
            warning = '等待时间较长，导出处理服务可能未启动'
          }
        }
      } else if (t.status === 'processing') {
        if (elapsed > PROCESSING_WARNING_SECONDS) {
          warning = '导出处理超时，可尝试删除后重新导出'
        }
      }

      const newWarning = warning || t._warning
      if (newWarning !== t._warning) {
        needsUpdate = true
        return { ...nextTask, _warning: newWarning }
      }
      return nextTask
    })

    if (needsUpdate) {
      this.setData({ list })
    }
  },

  onLoadMore() {
    if (!this.data.hasMore || this.data.loading) return
    this._loadList(false)
  },

  _enrichTask(task) {
    const st = STATUS_MAP[task.status] || {
      label: task.status || '未知状态',
      summary: '状态更新中',
      tone: 'neutral',
      glyph: '···',
      terminal: false,
    }
    const fmtText = FORMAT_MAP[task.file_format] || task.file_format || '文件'
    const expiry = formatExpiry(task.expires_at, task.status)
    const totalCount = Number(task.total_count || 0)
    const successCount = task.success_count == null ? null : Number(task.success_count)
    const skipCount = Number(task.skip_count || 0)

    // Initialize watch start time for non-terminal tasks
    if (!st.terminal && this._taskWatchStartedAt) {
      if (!this._taskWatchStartedAt.has(task.id)) {
        this._taskWatchStartedAt.set(task.id, Date.now())
      }
    }

    // Use server-provided status_message as initial warning
    var warning = task.status_message || null
    if (!warning && task.status === 'pending') {
      if (task.status_reason === 'processor_unavailable') {
        warning = '导出处理服务暂不可用'
      } else if (task.status_reason === 'pending_timeout') {
        warning = '等待时间较长，导出处理服务可能未启动'
      }
    }

    let resultText = ''
    if (successCount != null) {
      resultText = successCount + ' 道成功'
      if (skipCount > 0) resultText += ' · ' + skipCount + ' 道跳过'
    }

    return {
      ...task,
      statusLabel: st.label,
      statusSummary: st.summary,
      statusTone: st.tone,
      statusGlyph: st.glyph,
      _terminal: st.terminal,
      _warning: warning,
      fileSizeText: formatFileSize(task.file_size),
      formatText: fmtText,
      dateText: formatDateTime(task.completed_at || task.created_at),
      hasPreviousFile: !!task.file_size && ['pending', 'processing', 'failed'].includes(task.status),
      questionCountText: totalCount + ' 道题',
      resultText,
      displayFileName: task.file_name || '未命名导出文件',
      ...expiry,
    }
  },

  onToggleMore(e) {
    const taskId = Number(e.currentTarget.dataset.id)
    if (!taskId) return
    this.setData({
      expandedActionId: this.data.expandedActionId === taskId ? null : taskId,
    })
  },

  onBack() {
    const pages = getCurrentPages()
    const fallback = () => {
      wx.redirectTo({
        url: '/pages/export-config/export-config',
      })
    }

    if (pages && pages.length > 1) {
      wx.navigateBack({
        delta: 1,
        fail: fallback,
      })
      return
    }

    fallback()
  },

  onGoExport() {
    // Keep the empty records page in the stack so the export settings page
    // can return here normally. redirectTo previously replaced this page and
    // caused confusing back-navigation loops.
    wx.navigateTo({
      url: '/pages/export-config/export-config',
      fail: () => {
        wx.redirectTo({ url: '/pages/export-config/export-config' })
      },
    })
  },

  // ── Custom dialog ──

  _showDialog(options = {}) {
    if (this._dialogResolver) {
      this._dialogResolver({ confirm: false, cancel: true })
      this._dialogResolver = null
    }

    const tone = options.tone || 'default'
    this.setData({
      dialogVisible: true,
      dialogTitle: options.title || '提示',
      dialogContent: options.content || '',
      dialogConfirmText: options.confirmText || '确定',
      dialogCancelText: options.cancelText || '取消',
      dialogShowCancel: options.showCancel !== false,
      dialogTone: tone,
    })

    return new Promise((resolve) => {
      this._dialogResolver = resolve
    })
  },

  _finishDialog(result) {
    const resolver = this._dialogResolver
    this._dialogResolver = null
    this.setData({ dialogVisible: false })
    if (resolver) resolver(result)
  },

  onDialogConfirm() {
    this._finishDialog({ confirm: true, cancel: false })
  },

  onDialogCancel() {
    this._finishDialog({ confirm: false, cancel: true })
  },

  onDialogMaskTap() {
    // Tapping the mask does not dismiss the dialog.
  },

  onDialogPanelTap() {},

  // ── Preview (wx.openDocument) ──

  _previewCacheVersion(task) {
    if (!task) return ''
    return [
      Number(task.id) || 0,
      task.completed_at || '',
      Number(task.file_size) || 0,
      task.generator_version || '',
    ].join(':')
  },

  _invalidatePreviewCache(taskId) {
    const numericTaskId = Number(taskId)
    if (!numericTaskId) return

    if (this._previewFileCache) {
      const prefix = String(numericTaskId) + ':'
      Array.from(this._previewFileCache.keys()).forEach((key) => {
        if (String(key).indexOf(prefix) === 0) this._previewFileCache.delete(key)
      })
    }

    // Re-exporting or deleting a task makes every downloaded preview for that
    // task stale. Remove both the registry entry and the underlying temp file.
    previewTempFiles.removeByTaskId(numericTaskId).catch(function(err) {
      console.warn('[PREVIEW_TEMP] invalidate failed', err && (err.errMsg || err.message || err))
    })
  },

  _accessFile(filePath) {
    const fs = wx.getFileSystemManager && wx.getFileSystemManager()
    return new Promise(function(resolve, reject) {
      if (!fs || typeof fs.access !== 'function') {
        resolve()
        return
      }
      fs.access({ path: filePath, success: resolve, fail: reject })
    })
  },

  async _getPreviewFile(task) {
    const taskId = Number(task && task.id)
    const cacheKey = this._previewCacheVersion(task)
    const cachedPath = this._previewFileCache && this._previewFileCache.get(cacheKey)
    if (cachedPath) {
      try {
        await this._accessFile(cachedPath)
        previewTempFiles.touch(cachedPath)
        return cachedPath
      } catch (_) {
        this._previewFileCache.delete(cacheKey)
        previewTempFiles.forget(cachedPath)
      }
    }

    // Restore a still-valid temp path tracked by a previous page instance.
    // The host may have removed it already, so always verify with fs.access.
    const trackedPath = previewTempFiles.findByCacheKey(cacheKey)
    if (trackedPath) {
      try {
        await this._accessFile(trackedPath)
        if (this._previewFileCache) this._previewFileCache.set(cacheKey, trackedPath)
        previewTempFiles.touch(trackedPath)
        return trackedPath
      } catch (_) {
        previewTempFiles.forget(trackedPath)
      }
    }

    if (this._previewDownloadPromises && this._previewDownloadPromises.has(cacheKey)) {
      return this._previewDownloadPromises.get(cacheKey)
    }

    const downloadPromise = (async () => {
      const info = await exportApi.getDownloadInfo(taskId)
      const version = cacheKey
      const useAuth = info.method === 'stream'
      const url = useAuth
        ? exportApi.getFileUrl(taskId, version)
        : (info.url || exportApi.getFileUrl(taskId, version))
      const filePath = await this._downloadFile(url, useAuth)
      if (this._previewFileCache) this._previewFileCache.set(cacheKey, filePath)
      previewTempFiles.register(filePath, {
        taskId: taskId,
        cacheKey: cacheKey,
      })
      return filePath
    })()

    if (this._previewDownloadPromises) {
      this._previewDownloadPromises.set(cacheKey, downloadPromise)
    }
    try {
      return await downloadPromise
    } finally {
      if (this._previewDownloadPromises) this._previewDownloadPromises.delete(cacheKey)
    }
  },

  async onPreview(e) {
    const taskId = Number(e.currentTarget.dataset.id)
    if (!taskId || this.data.previewingTaskId) return
    const task = this.data.list.find(function(item) { return Number(item.id) === taskId })
    if (!task) return

    this.setData({ previewingTaskId: taskId })
    try {
      const filePath = await this._getPreviewFile(task)
      const fileType = task.file_format === 'docx' ? 'docx' : 'pdf'
      // wx.openDocument briefly hides and shows the page. Set the flag only
      // after the existing server file has been downloaded successfully, so a
      // download failure cannot suppress an unrelated future onShow refresh.
      this._suppressNextShowRefresh = true
      await new Promise(function(resolve, reject) {
        wx.openDocument({
          filePath,
          fileType,
          showMenu: true,
          success: resolve,
          fail: reject,
        })
      })
    } catch (err) {
      this._suppressNextShowRefresh = false
      this._invalidatePreviewCache(taskId)
      const content = task.file_format === 'docx'
        ? 'Word 文件暂时无法预览，可稍后重试或在支持 Word 的设备上打开。'
        : ((err && (err.message || err.errMsg)) || '文件暂时无法预览，请稍后重试。')
      await this._showDialog({
        title: '预览失败',
        content,
        confirmText: '知道了',
        showCancel: false,
        tone: 'danger',
      })
    } finally {
      // The document viewer makes this page temporarily hidden, so _pageAlive
      // is false at exactly the moment the open promise resolves. Clearing the
      // state must therefore depend on unload, not visibility.
      if (!this._pageDestroyed) {
        this.setData({ previewingTaskId: null })
      }
    }
  },

  _downloadFile(url, useAuth = true) {
    const header = {}
    if (useAuth) {
      const token = wx.getStorageSync('token')
      if (token) header.Authorization = 'Bearer ' + token
    }
    return new Promise(function(resolve, reject) {
      wx.downloadFile({
        url,
        header,
        success: function(res) {
          if (res.statusCode === 200 && res.tempFilePath) {
            resolve(res.tempFilePath)
            return
          }
          reject(new Error('下载失败（' + (res.statusCode || '未知状态') + '）'))
        },
        fail: function(err) {
          reject(new Error((err && err.errMsg) || '下载失败'))
        },
      })
    })
  },

  // ── Share ──

  /**
   * WeChat share lifecycle method. Triggered by <button open-type="share">.
   * Must return { title, path } — do NOT call wx.shareAppMessage().
   */
  onShareAppMessage(e) {
    this._suppressNextShowRefresh = true
    const taskId = e.target && e.target.dataset ? Number(e.target.dataset.id) : null
    const task = taskId ? this.data.list.find(t => Number(t.id) === taskId) : null
    return {
      title: (task && task.file_name) || '错题巩固练习',
      path: '/pages/export-records/export-records' + (task ? '?highlight=' + task.id : ''),
    }
  },

  // ── Delete ──

  async onDelete(e) {
    const taskId = e.currentTarget.dataset.id
    const result = await this._showDialog({
      title: '确认删除',
      content: '删除后将同时清理文件和导出记录，且无法恢复。',
      confirmText: '删除',
      cancelText: '取消',
      tone: 'danger',
    })
    if (!result.confirm) return

    try {
      await exportApi.deleteExport(taskId)
      if (this._statusSyncManager) {
        this._statusSyncManager.removeTask(taskId)
      }
      if (this._completedNotified) this._completedNotified.delete(taskId)
      this._invalidatePreviewCache(taskId)
      this.setData({
        list: this.data.list.filter(function(t) { return t.id !== taskId }),
        expandedActionId: this.data.expandedActionId === taskId
          ? null
          : this.data.expandedActionId,
      })
      wx.showToast({ title: '已删除', icon: 'success' })
    } catch (err) {
      await this._showDialog({
        title: '删除失败',
        content: (err && err.message) || '暂时无法删除该记录，请稍后重试。',
        confirmText: '知道了',
        showCancel: false,
        tone: 'danger',
      })
    }
  },

  // ── Retry ──

  onRetry(e) {
    const taskId = e.currentTarget.dataset.id
    const self = this
    exportApi.retryExport(taskId).then(function() {
      wx.showToast({ title: '已重新提交', icon: 'success' })
      self._loadList(true)
    }).catch(function(err) {
      wx.showToast({ title: err.message || '重试失败', icon: 'none' })
    })
  },

  // ── Re-export ──

  async onReExport(e) {
    const taskId = Number(e.currentTarget.dataset.id)
    if (!taskId || this.data.reExportingTaskId) return

    this._invalidatePreviewCache(taskId)
    this.setData({
      reExportingTaskId: taskId,
      previewingTaskId: null,
    })
    try {
      const task = await exportApi.reExport(taskId)
      if (!task || Number(task.id) !== taskId) {
        throw new Error('服务端未能原位更新导出记录')
      }

      this._mergeTask({
        ...task,
        id: taskId,
        status: task.status || 'pending',
      })
      this.setData({ expandedActionId: null, highlightId: taskId })
      this._restartStatusSync()
      wx.showToast({ title: '正在重新导出', icon: 'none' })
    } catch (err) {
      wx.showToast({ title: err.message || '重新导出失败', icon: 'none' })
    } finally {
      if (this._pageAlive) this.setData({ reExportingTaskId: null })
    }
  },
})

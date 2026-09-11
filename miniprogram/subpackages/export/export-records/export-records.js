/**
 * Export records page — list, sync, preview, share, delete, retry, re-export.
 *
 * Architecture:
 * - Single ``ExportStatusSyncManager`` per page instance (not one per task).
 * - WebSocket for real-time events + calibration polling from DB (always on).
 * - Task enrichment recomputed after every update.
 * - Completion toast shown only once per task via ``_completedNotified`` set.
 */
const exportApi = require('../services/export')
const requestApi = require('../../../utils/api')
const { ExportStatusSyncManager } = require('../services/export_status_sync')
const previewTempFiles = require('../../../utils/preview-temp-files')
const config = require('../../../config')

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

const SORT_MAP = {
  newest: '最新优先',
  oldest: '最早优先',
  original: '原练习顺序',
  random: '随机排序',
  knowledge_point: '知识点排序',
  question_type: '题型排序',
}

const GROUP_MAP = {
  none: '连续排列',
  subject: '按学科分区',
  chapter: '按章节分区',
  knowledge_point: '按知识点分区',
  question_type: '按题型分区',
}

const POSITION_MAP = {
  none: '不含',
  after_question: '逐题附',
  at_end: '末尾集中',
}

const SPACE_MAP = {
  compact: '紧凑留白',
  standard: '标准留白',
  spacious: '宽松留白',
}

const TERMINAL_STATES = ['completed', 'failed', 'expired']
const PENDING_WARNING_SECONDS = 30
const PROCESSING_WARNING_SECONDS = 300  // 5 minutes

function pad2(value) {
  return Number(value) < 10 ? '0' + Number(value) : String(value)
}

// Export timestamps follow the project's server-time convention: naive ISO
// values are UTC, while product-facing time is fixed to China Standard Time
// (UTC+8) and must not change with the device timezone.
const CHINA_OFFSET_MS = 8 * 60 * 60 * 1000

/**
 * Parse API timestamps consistently on iOS and Android.
 * The backend stores/returns naive timestamps in UTC, so an ISO value without
 * an explicit timezone must be interpreted as UTC instead of device local time.
 */
function parseDateValue(value) {
  if (!value) return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }

  const raw = String(value).trim()
  if (!raw) return null

  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  let normalized = raw.replace(' ', 'T')
  if (!hasTimezone) normalized += 'Z'

  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Return a Date whose UTC fields represent the China wall-clock time. */
function toChinaWallDate(date) {
  return new Date(date.getTime() + CHINA_OFFSET_MS)
}

function formatDateTime(value) {
  const date = parseDateValue(value)
  if (!date) return value ? String(value) : ''

  const china = toChinaWallDate(date)
  return [
    china.getUTCFullYear() + '年',
    china.getUTCMonth() + 1 + '月',
    china.getUTCDate() + '日 ',
    pad2(china.getUTCHours()) + ':' + pad2(china.getUTCMinutes()),
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

  const china = toChinaWallDate(date)
  return {
    expiresText: '有效期至 ' + (china.getUTCMonth() + 1) + '月' + china.getUTCDate() + '日 ' +
      pad2(china.getUTCHours()) + ':' + pad2(china.getUTCMinutes()),
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
    totalRecords: 0,
    hasMore: false,
    loading: false,
    highlightId: null,
    expandedActionId: null,
    previewingTaskId: null,
    reExportingTaskId: null,
    retryingTaskId: null,
    deletingTaskId: null,
    skeletonItems: [1, 2],

    // Safe initial state: do not expose export records/actions until the
    // capability endpoint explicitly confirms PDF export is available.
    exportAvailable: false,
    exportCapabilityChecked: false,
    exportCapabilityLoading: false,
    exportCapabilityRetryable: false,
    exportUnavailableText: '当前导出功能不可用',

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
  _loadPromiseReset: false,
  _listRequestId: 0,
  _completedNotified: null,
  _taskWatchStartedAt: null,  // Map<taskId, timestamp> for timeout detection
  _watchTimer: null,  // periodic check for long-running tasks
  _dialogResolver: null,
  _previewFileCache: null,
  _previewDownloadPromises: null,
  _suppressNextShowRefresh: false,
  _pageDestroyed: false,
  _capabilityPromise: null,
  _capabilityRequestId: 0,

  onLoad(options) {
    this._pageDestroyed = false
    this._pageAlive = true
    this._completedNotified = new Set()
    this._taskWatchStartedAt = new Map()
    this._previewFileCache = new Map()
    this._previewDownloadPromises = new Map()
    this._suppressNextShowRefresh = false
    if (options.highlight) {
      this.setData({ highlightId: parseInt(options.highlight, 10) })
    }

    this._checkExportCapability()
  },

  onShow() {
    this._pageAlive = true

    // wx.openDocument hides the page while the document viewer is active.
    // Always clear the transient button state when the page becomes visible
    // again, including after re-exporting or returning from a failed open.
    if (this.data.previewingTaskId !== null) {
      this.setData({ previewingTaskId: null })
    }
    if (!this.data.exportAvailable) {
      this._checkExportCapability()
      return
    }

    this._startWatchTimer()

    if (!this._hasLoadedOnce) {
      // Capability checks can finish while the page is hidden. In that case the
      // initial list request is intentionally skipped and must be started here.
      this._loadList(true)
    } else {
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
    this._capabilityRequestId++
    this._listRequestId++
    this._loadPromise = null
    this._loadPromiseReset = false
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

  async _checkExportCapability(force = false) {
    if (this._pageDestroyed) return false
    if (this._capabilityPromise && !force) return this._capabilityPromise

    const requestId = ++this._capabilityRequestId
    this.setData({
      exportAvailable: false,
      exportCapabilityChecked: false,
      exportCapabilityLoading: true,
      exportCapabilityRetryable: true,
      exportUnavailableText: '当前导出功能不可用',
      loading: false,
    })
    this._stopWatchTimer()
    this._destroySyncManager()

    if (config.WRONG_BOOK_EXPORT_ENABLED !== true) {
      this.setData({
        exportCapabilityChecked: true,
        exportCapabilityLoading: false,
        exportCapabilityRetryable: false,
        exportUnavailableText: '该功能暂未开放，请稍后再试。',
      })
      return false
    }

    const check = async () => {
      try {
        const capability = await exportApi.getCapabilities()
        if (this._pageDestroyed || requestId !== this._capabilityRequestId) return false
        const available = !!(
          capability &&
          capability.export_enabled === true &&
          capability.pdf_enabled === true
        )

        this.setData({
          exportAvailable: available,
          exportCapabilityChecked: true,
          exportCapabilityLoading: false,
          exportCapabilityRetryable: !available,
          exportUnavailableText: available
            ? ''
            : exportApi.getExportCapabilityErrorMessage(null, capability),
        })

        if (!available) return false
        // If the capability response arrives while hidden, keep only the
        // capability state. onShow will start timers/sync and perform the first
        // list load, avoiding background work that immediately gets torn down.
        if (this._pageAlive) {
          this._createSyncManager()
          this._startWatchTimer()
          await this._loadList(true)
        }
        return true
      } catch (error) {
        if (this._pageDestroyed || requestId !== this._capabilityRequestId) return false
        this.setData({
          exportAvailable: false,
          exportCapabilityChecked: true,
          exportCapabilityLoading: false,
          exportCapabilityRetryable: true,
          exportUnavailableText: exportApi.getExportCapabilityErrorMessage(error),
        })
        return false
      }
    }

    this._capabilityPromise = check()
    try {
      return await this._capabilityPromise
    } finally {
      if (requestId === this._capabilityRequestId) this._capabilityPromise = null
    }
  },

  onRetryCapability() {
    if (this.data.exportCapabilityLoading) return
    this._checkExportCapability(true)
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
    const numericTaskId = Number(taskId)
    if (!numericTaskId) return
    const normalized = this._normalizeUpdate(numericTaskId, data || {})
    let currentTask = this.data.list.find(t => Number(t.id) === numericTaskId)

    // Calibration requests often return the exact same task snapshot. Avoid
    // replacing the whole list in setData for no-op updates; on long-running
    // exports that repeated full-list diffing can make the page visibly janky.
    if (currentTask && this._isStatusUpdateUnchanged(currentTask, normalized)) {
      return
    }

    const incomingCompleted = normalized.status === 'completed'
    const currentTerminal = currentTask && TERMINAL_STATES.includes(currentTask.status)
    if (incomingCompleted && !currentTerminal) {
      // WebSocket events are partial, while calibration GET responses are already
      // complete. Only perform the extra detail request for a partial WS event.
      const hasFullTaskPayload = data && data.file_name !== undefined && data.has_file !== undefined
      if (!hasFullTaskPayload) {
        try {
          const full = await exportApi.getExport(numericTaskId)
          if (!this._pageAlive) return
          Object.assign(normalized, full || {}, { id: numericTaskId })
        } catch (e) {
          if (!this._pageAlive) return
          // Use what we have
        }
      }
    }

    if (!this._pageAlive) return
    // The detail request above can be slower than another WS/calibration update.
    // Re-read the current task and reject an older snapshot instead of allowing
    // a late response to regress the UI.
    currentTask = this.data.list.find(t => Number(t.id) === numericTaskId)
    if (currentTask && this._isTaskSnapshotOlder(normalized, currentTask)) return

    const wasTerminal = currentTask && TERMINAL_STATES.includes(currentTask.status)
    const finalCompleted = normalized.status === 'completed'

    // Enrich and merge
    const enriched = this._enrichTask({ ...(currentTask || {}), ...normalized, id: numericTaskId })
    this._mergeTask(enriched)

    // Show completion toast once per task
    if (finalCompleted && !wasTerminal) {
      if (!this._completedNotified.has(numericTaskId)) {
        this._completedNotified.add(numericTaskId)
        wx.showToast({ title: '导出完成', icon: 'success' })
      }
    }
  },

  /**
   * Normalize a status update to a consistent shape.
   */
  _normalizeUpdate(taskId, data) {
    data = data || {}
    const numericTaskId = Number(taskId)
    const base = { id: numericTaskId }
    // WS events use task_id/status; API responses use id/status
    if (data.task_id !== undefined && data.id === undefined) {
      base.id = Number(data.task_id)
    }

    const normalized = { ...base, ...data, id: numericTaskId }

    // status_message/status_reason are transient diagnostics for the pending
    // state. WebSocket updates are partial, so explicitly clear them once a
    // task starts processing or reaches a terminal state; otherwise the old
    // "processor unavailable" warning can remain visible after progress has
    // already resumed.
    if (normalized.status && normalized.status !== 'pending') {
      if (data.status_message === undefined) normalized.status_message = null
      if (data.status_reason === undefined) normalized.status_reason = null
    }

    return normalized
  },

  _isStatusUpdateUnchanged(current, incoming) {
    const fields = [
      'status', 'success_count', 'skip_count', 'file_size', 'file_name',
      'error_message', 'status_reason', 'status_message', 'completed_at',
      'expires_at', 'updated_at', 'version', 'has_file', 'is_reexporting',
      'reexport_failed',
    ]

    return fields.every(function(field) {
      return incoming[field] === undefined || incoming[field] === current[field]
    })
  },

  _isTaskSnapshotOlder(incoming, current) {
    if (!incoming || !current) return false

    const incomingVersion = Number(incoming.version)
    const currentVersion = Number(current.version)
    if (Number.isFinite(incomingVersion) && Number.isFinite(currentVersion) && incomingVersion !== currentVersion) {
      return incomingVersion < currentVersion
    }

    const incomingUpdated = parseDateValue(incoming.updated_at || incoming.completed_at || incoming.created_at)
    const currentUpdated = parseDateValue(current.updated_at || current.completed_at || current.created_at)
    if (incomingUpdated && currentUpdated && incomingUpdated.getTime() !== currentUpdated.getTime()) {
      return incomingUpdated.getTime() < currentUpdated.getTime()
    }

    // Last-resort protection when an older endpoint omits version/update time.
    // Do not regress a terminal task to a normal pending/processing snapshot.
    return TERMINAL_STATES.includes(current.status) &&
      !TERMINAL_STATES.includes(incoming.status) &&
      !incoming.is_reexporting
  },

  /**
   * Merge a single task update into the list. Preserves fields the update
   * doesn't carry (WS events are partial).
   */
  _mergeTask(updated) {
    if (this._pageDestroyed) return
    const updatedId = Number(updated && updated.id)
    if (!updatedId) return
    const list = this.data.list.map(t => {
      if (Number(t.id) !== updatedId) return t
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

    const existed = this.data.list.some(item => Number(item.id) === taskId)
    const enriched = this._enrichTask({ ...task, id: taskId })
    const list = [enriched].concat(
      this.data.list.filter(item => Number(item.id) !== taskId)
    )
    this.setData({
      list,
      totalRecords: existed ? this.data.totalRecords : this.data.totalRecords + 1,
      highlightId: taskId,
      expandedActionId: null,
    })
    this._restartStatusSync()
  },

  // ── List loading ──

  async _loadList(reset = false) {
    if (!this._pageAlive || !this.data.exportAvailable) return null

    // A foreground reset is allowed to supersede an in-flight load-more. This
    // matters when the user leaves/returns while pagination is still pending.
    if (this._loadPromise) {
      if (!reset || this._loadPromiseReset) return this._loadPromise
      this._listRequestId++
      this._loadPromise = null
      this._loadPromiseReset = false
    }
    if (this.data.loading && !reset) return null

    this.setData({ loading: true })
    const requestId = ++this._listRequestId
    const page = reset ? 1 : this.data.page + 1

    const loadPromise = (async () => {
      try {
        const res = await exportApi.listExports(page, 20)
        if (this._pageDestroyed || requestId !== this._listRequestId) return null

        const tasks = res.items || []
        const currentById = new Map(
          (this.data.list || []).map((task) => [Number(task.id), task])
        )
        const enriched = tasks.map((task) => {
          const incoming = this._enrichTask(task)
          const current = currentById.get(Number(incoming.id))
          return current && this._isTaskSnapshotOlder(incoming, current) ? current : incoming
        })
        const combined = reset ? enriched : (this.data.list || []).concat(enriched)
        const seen = {}
        const list = combined.filter(function(item) {
          const id = Number(item.id)
          if (!id || seen[id]) return false
          seen[id] = true
          return true
        })
        const responseTotal = Number(res.total)
        const totalRecords = Number.isFinite(responseTotal)
          ? responseTotal
          : list.length

        this.setData({
          list,
          totalRecords,
          page: Number(res.page) || page,
          hasMore: list.length < totalRecords,
          loading: false,
        })

        this._hasLoadedOnce = true
        this._restartStatusSync()
        return res
      } catch (err) {
        if (this._pageDestroyed || requestId !== this._listRequestId) return null
        this.setData({ loading: false })
        if (this._pageAlive) {
          wx.showToast({ title: '加载失败', icon: 'none' })
        }
        return null
      }
    })()

    this._loadPromise = loadPromise
    this._loadPromiseReset = reset
    try {
      return await loadPromise
    } finally {
      if (this._loadPromise === loadPromise) {
        this._loadPromise = null
        this._loadPromiseReset = false
      }
    }
  },

  /**
   * Periodic watch timer — checks task durations and updates warnings.
   * Runs every 10 seconds while page is alive.
   */
  _startWatchTimer() {
    this._stopWatchTimer()
    if (!this._pageAlive || this._pageDestroyed) return
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
          warning = '等待时间较长，任务仍在导出队列中'
        }
      } else if (t.status === 'processing') {
        if (elapsed > PROCESSING_WARNING_SECONDS) {
          warning = '生成时间较长，任务仍在处理中'
        }
      }

      // Recompute the warning from the current task state instead of retaining
      // a previous pending-state warning forever. This also removes stale
      // service-unavailable copy as soon as the task begins processing.
      const newWarning = warning || this._getTaskStatusWarning(t)
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
    if (!this.data.exportAvailable) return
    if (!this.data.hasMore || this.data.loading) return
    this._loadList(false)
  },

  _getTaskStatusWarning(task) {
    if (!task || !['pending', 'processing'].includes(task.status)) return null

    const message = task.status_message ? String(task.status_message).trim() : ''
    if (!message) return null

    // Processor-health diagnostics are an internal snapshot, not the task's
    // final result. Showing them on an active task is misleading because the
    // worker may pick up and complete the task immediately afterwards.
    const misleadingProcessorWarning =
      /导出处理服务.*(?:不可用|未启动)/.test(message) ||
      /处理服务可能未启动/.test(message)

    return misleadingProcessorWarning ? null : message
  },

  _enrichTask(task) {
    task = task || {}
    const numericTaskId = Number(task.id)
    const normalizedTaskId = numericTaskId > 0 ? numericTaskId : task.id
    const reexportFailed = !!(task.reexport_failed || task.error_code === 'reexport_failed')
    const reexporting = !!(
      task.is_reexporting ||
      (task.error_code === 'reexporting' && ['pending', 'processing'].includes(task.status))
    )
    let st = STATUS_MAP[task.status] || {
      label: task.status || '未知状态',
      summary: '状态更新中',
      tone: 'neutral',
      glyph: '···',
      terminal: false,
    }
    if (reexportFailed) {
      st = {
        label: '新版生成失败',
        summary: '已保留上一版文件，可继续打开',
        tone: 'warning',
        glyph: '!',
        terminal: true,
      }
    } else if (reexporting) {
      st = {
        ...st,
        label: task.status === 'processing' ? '正在重新导出' : '等待重新导出',
        summary: '上一版文件仍可预览',
      }
    }
    const fmtText = FORMAT_MAP[task.file_format] || task.file_format || '文件'
    const expiry = formatExpiry(task.expires_at, task.status)
    const totalCount = Number(task.total_count || 0)
    const successCount = task.success_count == null ? null : Number(task.success_count)
    const skipCount = Number(task.skip_count || 0)

    // Initialize watch start time for non-terminal tasks
    if (!st.terminal && this._taskWatchStartedAt) {
      if (!this._taskWatchStartedAt.has(normalizedTaskId)) {
        const createdAt = parseDateValue(task.created_at)
        this._taskWatchStartedAt.set(
          normalizedTaskId,
          createdAt ? createdAt.getTime() : Date.now()
        )
      }
    } else if (st.terminal && this._taskWatchStartedAt) {
      this._taskWatchStartedAt.delete(normalizedTaskId)
    }

    // Only expose task-specific, actionable status messages. Processor
    // availability diagnostics are deliberately hidden while the task is
    // pending/processing because they can become stale before the next render.
    var warning = this._getTaskStatusWarning(task)
    if (!warning && task.status === 'pending' && task.status_reason === 'pending_timeout') {
      warning = '等待时间较长，任务仍在导出队列中'
    }

    let resultText = ''
    if (successCount != null) {
      resultText = successCount + ' 道已导出'
      if (skipCount > 0) resultText += ' · ' + skipCount + ' 道跳过'
    }
    const layoutSummary = this._buildLayoutSummary(task)
    const hasPreviousFile = !!(
      reexporting &&
      (task.has_file || task.file_size)
    )

    return {
      ...task,
      id: normalizedTaskId,
      is_reexporting: reexporting,
      reexport_failed: reexportFailed,
      visualStatus: reexportFailed ? 'warning' : task.status,
      statusLabel: st.label,
      statusSummary: st.summary,
      statusTone: st.tone,
      statusGlyph: st.glyph,
      _terminal: st.terminal,
      _warning: warning,
      fileSizeText: formatFileSize(task.file_size),
      formatText: fmtText,
      dateText: formatDateTime(task.completed_at || task.created_at),
      hasPreviousFile,
      questionCountText: totalCount + ' 道题',
      resultText,
      displayFileName: task.file_name || '未命名导出文件',
      layoutSummary,
      ...expiry,
    }
  },

  _buildLayoutSummary(task) {
    const sortText = SORT_MAP[task.sort_by] || ''
    const groupText = GROUP_MAP[task.group_by] || ''
    const answer = task.answer_position || 'none'
    const analysis = task.analysis_position || 'none'
    let contentText = ''
    if (answer === analysis) {
      if (answer === 'at_end') contentText = '答案解析置于末尾'
      else if (answer === 'after_question') contentText = '逐题附答案解析'
      else contentText = '不含答案解析'
    } else {
      contentText = (POSITION_MAP[answer] || '') + '答案 · ' +
        (POSITION_MAP[analysis] || '') + '解析'
    }
    const spaceText = SPACE_MAP[task.space_style] || ''
    return [sortText, groupText, contentText, spaceText].filter(Boolean).join(' · ')
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
        url: this.data.exportAvailable
          ? '/subpackages/export/export-config/export-config'
          : '/subpackages/study/wrong-book/wrong-book',
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
    if (!this.data.exportAvailable) {
      wx.showToast({
        title: this.data.exportUnavailableText || '当前导出功能不可用',
        icon: 'none',
      })
      return
    }
    // Keep the empty records page in the stack so the export settings page
    // can return here normally. redirectTo previously replaced this page and
    // caused confusing back-navigation loops.
    wx.navigateTo({
      url: '/subpackages/export/export-config/export-config',
      fail: () => {
        wx.redirectTo({ url: '/subpackages/export/export-config/export-config' })
      },
    })
  },

  // ── Custom dialog ──

  _showDialog(options = {}) {
    if (this._pageDestroyed) {
      return Promise.resolve({ confirm: false, cancel: true })
    }
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
      const useApiStream = info.method === 'stream'
      const url = useApiStream
        ? exportApi.getFileUrl(taskId, version)
        : (info.url || exportApi.getFileUrl(taskId, version))

      // Authenticated export files use the same wx.request transport as the
      // rest of the API, then persist the returned ArrayBuffer locally before
      // wx.openDocument is called. This avoids a separate wx.downloadFile
      // connection to the API host, which can fail on real devices even while
      // normal API requests and the export task itself are working correctly.
      const filePath = useApiStream
        ? await this._requestStreamFile(url, task, cacheKey)
        : await this._downloadFile(url, false)

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
      if (this._pageDestroyed) return
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
        : this._getPreviewErrorMessage(err)
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

  _getPreviewErrorMessage(err) {
    const statusCode = Number(err && err.statusCode)
    if (statusCode === 401) return '登录状态已过期，请重新登录后再打开文件。'
    if (statusCode === 404 || statusCode === 410) return '导出文件不存在或已过期，请重新导出。'
    return '文件下载或打开失败，请检查网络后重试。'
  },

  _buildPreviewFilePath(task, cacheKey) {
    const userDataPath = wx.env && wx.env.USER_DATA_PATH
    if (!userDataPath) return ''
    const taskId = Number(task && task.id) || Date.now()
    const extension = task && task.file_format === 'docx' ? 'docx' : 'pdf'
    const version = String(cacheKey || Date.now())
      .replace(/[^a-zA-Z0-9_-]/g, '_')
      .slice(-72)
    return userDataPath + '/export-preview-' + taskId + '-' + version + '.' + extension
  },

  _writePreviewFile(filePath, data) {
    const fs = wx.getFileSystemManager && wx.getFileSystemManager()
    return new Promise(function(resolve, reject) {
      if (!fs || typeof fs.writeFile !== 'function' || !filePath) {
        reject(new Error('当前微信版本无法保存预览文件'))
        return
      }
      if (!data || typeof data.byteLength !== 'number' || data.byteLength <= 0) {
        reject(new Error('导出文件内容为空'))
        return
      }
      fs.writeFile({
        filePath: filePath,
        data: data,
        success: function() { resolve(filePath) },
        fail: function(err) {
          reject(new Error((err && err.errMsg) || '保存预览文件失败'))
        },
      })
    })
  },

  _requestFileBuffer(url, token, traceId) {
    const activeTraceId = traceId || requestApi.createTraceId()
    const header = {
      'X-Trace-ID': activeTraceId,
      'X-Request-ID': requestApi.createRequestId(),
    }
    if (token) header.Authorization = 'Bearer ' + token

    return new Promise(function(resolve, reject) {
      wx.request({
        url: url,
        method: 'GET',
        header: header,
        responseType: 'arraybuffer',
        timeout: 60000,
        success: function(res) {
          if (res.statusCode === 200 && res.data && typeof res.data.byteLength === 'number') {
            resolve(res.data)
            return
          }
          const error = new Error('文件请求失败（' + (res.statusCode || '未知状态') + '）')
          error.statusCode = Number(res.statusCode) || 0
          reject(error)
        },
        fail: function(err) {
          reject(new Error((err && err.errMsg) || '文件请求失败'))
        },
      })
    })
  },

  async _requestStreamFile(url, task, cacheKey) {
    const traceId = requestApi.createTraceId()
    const filePath = this._buildPreviewFilePath(task, cacheKey)
    if (!filePath) return this._downloadFile(url, true, traceId)

    const tokenReady = await requestApi.ensureValidToken(traceId)
    if (!tokenReady) {
      const error = new Error('登录状态已过期')
      error.statusCode = 401
      throw error
    }

    let token = wx.getStorageSync('token')
    let data
    try {
      data = await this._requestFileBuffer(url, token, traceId)
    } catch (err) {
      if (Number(err && err.statusCode) === 401) {
        token = await requestApi.forceRefreshToken()
        data = await this._requestFileBuffer(url, token, traceId)
      } else {
        // Some older base-library versions handle binary responses more
        // reliably through downloadFile. Keep it as a compatibility fallback.
        return this._downloadFile(url, true, traceId)
      }
    }

    return this._writePreviewFile(filePath, data)
  },

  _downloadFile(url, useAuth = true, traceId = '') {
    const header = {}
    if (useAuth) {
      header['X-Trace-ID'] = traceId || requestApi.createTraceId()
      header['X-Request-ID'] = requestApi.createRequestId()
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
      path: '/subpackages/export/export-records/export-records' + (task ? '?highlight=' + task.id : ''),
    }
  },

  // ── Delete ──

  async onDelete(e) {
    const taskId = Number(e.currentTarget.dataset.id)
    if (!taskId || this.data.deletingTaskId) return
    const result = await this._showDialog({
      title: '确认删除',
      content: '删除后将同时清理文件和导出记录，且无法恢复。',
      confirmText: '删除',
      cancelText: '取消',
      tone: 'danger',
    })
    if (!result.confirm) return

    this.setData({ deletingTaskId: taskId })
    try {
      await exportApi.deleteExport(taskId)
      if (this._pageDestroyed) return
      if (this._statusSyncManager) {
        this._statusSyncManager.removeTask(taskId)
      }
      if (this._completedNotified) this._completedNotified.delete(taskId)
      this._invalidatePreviewCache(taskId)
      this.setData({
        list: this.data.list.filter(function(t) { return Number(t.id) !== taskId }),
        totalRecords: Math.max(0, this.data.totalRecords - 1),
        expandedActionId: this.data.expandedActionId === taskId
          ? null
          : this.data.expandedActionId,
      })
      wx.showToast({ title: '已删除', icon: 'success' })
    } catch (err) {
      if (this._pageDestroyed) return
      await this._showDialog({
        title: '删除失败',
        content: (err && err.message) || '暂时无法删除该记录，请稍后重试。',
        confirmText: '知道了',
        showCancel: false,
        tone: 'danger',
      })
    } finally {
      if (!this._pageDestroyed) this.setData({ deletingTaskId: null })
    }
  },

  // ── Retry ──

  async onRetry(e) {
    const taskId = Number(e.currentTarget.dataset.id)
    if (!taskId || this.data.retryingTaskId) return
    this.setData({ retryingTaskId: taskId })
    try {
      const task = await exportApi.retryExport(taskId)
      if (this._pageDestroyed) return
      if (!task || !task.id) throw new Error('服务端未返回新的导出任务')
      this._upsertTaskAtTop(task)
      wx.showToast({ title: '已重新提交', icon: 'success' })
    } catch (err) {
      if (this._pageDestroyed) return
      wx.showToast({ title: err.message || '重试失败', icon: 'none' })
    } finally {
      if (!this._pageDestroyed) this.setData({ retryingTaskId: null })
    }
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
      if (this._pageDestroyed) return
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
      if (this._pageDestroyed) return
      wx.showToast({ title: err.message || '重新导出失败', icon: 'none' })
    } finally {
      if (this._pageAlive) this.setData({ reExportingTaskId: null })
    }
  },
})

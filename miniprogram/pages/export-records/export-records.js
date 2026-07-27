/**
 * Export records page — list, sync, preview, save, share, delete, retry, re-export.
 *
 * Architecture:
 * - Single ``ExportStatusSyncManager`` per page instance (not one per task).
 * - WebSocket for real-time events + calibration polling from DB (always on).
 * - Task enrichment recomputed after every update.
 * - Completion toast shown only once per task via ``_completedNotified`` set.
 */
const exportApi = require('../../services/export')
const { ExportStatusSyncManager } = require('../../services/export_status_sync')

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
const EXPORT_STORAGE_KEY = 'saved_export_files_v2'
const EXPORT_STORAGE_DIR = 'exports'
const MAX_SAVED_EXPORTS = 5

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
    savingTaskId: null,
    reExportingTaskId: null,
    skeletonItems: [1, 2],
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

  onLoad(options) {
    this._pageAlive = true
    this._completedNotified = new Set()
    this._taskWatchStartedAt = new Map()
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
    this._startWatchTimer()

    if (this._hasLoadedOnce) {
      // On return from background or other pages: force-refresh immediately
      this._loadList(true)
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
    this._pageAlive = false
    this._stopWatchTimer()
    this._destroySyncManager()
    if (this._completedNotified) this._completedNotified.clear()
    if (this._taskWatchStartedAt) {
      this._taskWatchStartedAt.clear()
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
      // Re-enrich the complete merged task so partial WebSocket events do not
      // overwrite formatted fields with empty fallback values.
      return this._enrichTask({ ...t, ...updated })
    })
    this.setData({ list })
  },

  /**
   * Insert or replace a task at the top of the list.
   * Re-export returns the newly-created pending task directly, so rendering
   * that response avoids a race where an immediate list refresh still shows
   * only the completed source task.
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
      dateText: formatDateTime(task.created_at),
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
    wx.redirectTo({
      url: '/pages/export-config/export-config',
    })
  },

  // ── Preview (wx.openDocument) ──

  async onPreview(e) {
    const taskId = e.currentTarget.dataset.id
    if (!taskId) return

    try {
      const info = await exportApi.getDownloadInfo(taskId)

      let filePath = ''
      if (info.method === 'stream') {
        const url = exportApi.getFileUrl(taskId)
        const dl = await this._downloadFile(url, true)
        filePath = dl
      } else if (info.url) {
        const dl = await this._downloadFile(info.url, false)
        filePath = dl
      } else {
        wx.showToast({ title: '无法获取文件', icon: 'none' })
        return
      }

      // Determine file type from task format or file extension
      const task = this.data.list.find(function(t) { return t.id === taskId })
      const fileFormat = (task && task.file_format) || 'pdf'
      const fileType = fileFormat === 'docx' ? 'docx' : 'pdf'

      wx.openDocument({
        filePath,
        fileType: fileType,
        success: function() { console.log('Preview success') },
        fail: function(err) {
          console.error('Preview failed', err)
          const msg = fileType === 'docx'
            ? 'Word 文件预览失败，请尝试保存后使用 WPS 或 Word 打开'
            : '预览失败，请稍后重试'
          wx.showToast({ title: msg, icon: 'none' })
        },
      })
    } catch (err) {
      wx.showToast({ title: err.message || '预览失败', icon: 'none' })
    }
  },

  _downloadFile(url, useAuth = true) {
    const header = {}
    if (useAuth) {
      const token = wx.getStorageSync('token')
      if (token) header['Authorization'] = 'Bearer ' + token
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

  _sanitizeLocalFileName(fileName, fileFormat) {
    const ext = fileFormat === 'docx' ? 'docx' : 'pdf'
    let safe = String(fileName || ('错题巩固练习.' + ext))
      .replace(/[\\/:*?"<>|\x00-\x1f]/g, '')
      .replace(/^\s+|\s+$/g, '')
    if (!safe) safe = '错题巩固练习.' + ext
    if (!new RegExp('\\.' + ext + '$', 'i').test(safe)) {
      safe += '.' + ext
    }
    return safe
  },

  _fsCall(method, options) {
    const fs = wx.getFileSystemManager()
    return new Promise(function(resolve, reject) {
      if (!fs || typeof fs[method] !== 'function') {
        reject(new Error('当前微信版本不支持文件保存'))
        return
      }
      fs[method](Object.assign({}, options, {
        success: resolve,
        fail: reject,
      }))
    })
  },

  _unlinkFile(filePath) {
    if (!filePath) return Promise.resolve()
    return this._fsCall('unlink', { filePath }).catch(function() {})
  },

  _ensureExportStorageDir() {
    const dirPath = wx.env.USER_DATA_PATH + '/' + EXPORT_STORAGE_DIR
    return this._fsCall('mkdir', { dirPath, recursive: true })
      .catch(function(err) {
        const msg = (err && err.errMsg) || ''
        if (/exist/i.test(msg)) return
        throw err
      })
      .then(function() { return dirPath })
  },

  _readSavedExportIndex() {
    const raw = wx.getStorageSync(EXPORT_STORAGE_KEY)
    if (!Array.isArray(raw)) return []
    return raw.filter(function(item) {
      return item && typeof item.filePath === 'string'
    })
  },

  _writeSavedExportIndex(items) {
    try {
      wx.setStorageSync(EXPORT_STORAGE_KEY, Array.isArray(items) ? items : [])
    } catch (_) {}
  },

  _isStorageQuotaError(err) {
    const msg = String((err && (err.errMsg || err.message)) || '')
    return /maximum size|storage limit|quota|空间.*满|存储.*满/i.test(msg)
  },

  async _listDirFiles(dirPath) {
    try {
      const res = await this._fsCall('readdir', { dirPath })
      return (res && res.files) || []
    } catch (_) {
      return []
    }
  },

  async _clearManagedExportFiles() {
    const indexed = this._readSavedExportIndex()
    const targets = indexed.map(function(item) { return item.filePath })
    const exportDir = wx.env.USER_DATA_PATH + '/' + EXPORT_STORAGE_DIR
    const managedNames = await this._listDirFiles(exportDir)
    managedNames.forEach(function(name) {
      targets.push(exportDir + '/' + name)
    })

    // Clean legacy files saved by the previous implementation directly under
    // USER_DATA_PATH. Only recognisable export documents are removed.
    const rootFiles = await this._listDirFiles(wx.env.USER_DATA_PATH)
    rootFiles.forEach(function(name) {
      if (/^(?:错题|export[_-]).*\.(?:pdf|docx)$/i.test(name)) {
        targets.push(wx.env.USER_DATA_PATH + '/' + name)
      }
    })

    const unique = Array.from(new Set(targets))
    await Promise.all(unique.map((filePath) => this._unlinkFile(filePath)))

    // wx.saveFile from older versions stored files in WeChat's saved-file
    // area. Remove only PDF/Word entries so unrelated app data is preserved.
    try {
      const saved = await this._fsCall('getSavedFileList', {})
      const documentFiles = ((saved && saved.fileList) || []).filter(function(item) {
        return item && /\.(?:pdf|docx)$/i.test(item.filePath || '')
      })
      await Promise.all(documentFiles.map((item) => {
        return this._fsCall('removeSavedFile', { filePath: item.filePath }).catch(function() {})
      }))
    } catch (_) {}

    this._writeSavedExportIndex([])
  },

  async _rememberSavedExport(filePath, taskId, fileName) {
    const now = Date.now()
    const current = this._readSavedExportIndex()
      .filter(function(item) { return item.filePath !== filePath })
    current.unshift({ filePath, taskId, fileName, savedAt: now })

    const keep = current.slice(0, MAX_SAVED_EXPORTS)
    const remove = current.slice(MAX_SAVED_EXPORTS)
    await Promise.all(remove.map((item) => this._unlinkFile(item.filePath)))
    this._writeSavedExportIndex(keep)
  },

  /**
   * Persist a downloaded file in the app's managed export directory.
   * Uses FileSystemManager.saveFile (the supported API), keeps only a small
   * number of historical exports, and clears prior app-generated export files
   * once when WeChat reports that the private file quota is full.
   */
  async _persistDownloadedFile(tempFilePath, fileName, taskId) {
    const exportDir = await this._ensureExportStorageDir()
    const stableName = 'export_' + taskId + '_' + fileName
    const targetPath = exportDir + '/' + stableName

    const saveOnce = async () => {
      await this._unlinkFile(targetPath)
      const res = await this._fsCall('saveFile', {
        tempFilePath,
        filePath: targetPath,
      })
      return (res && res.savedFilePath) || targetPath
    }

    try {
      const savedPath = await saveOnce()
      await this._rememberSavedExport(savedPath, taskId, fileName)
      return savedPath
    } catch (err) {
      if (!this._isStorageQuotaError(err)) throw err
      await this._clearManagedExportFiles()
      await this._ensureExportStorageDir()
      const savedPath = await saveOnce()
      await this._rememberSavedExport(savedPath, taskId, fileName)
      return savedPath
    }
  },

  _openSavedDocument(filePath, fileFormat) {
    return new Promise(function(resolve, reject) {
      wx.openDocument({
        filePath,
        fileType: fileFormat === 'docx' ? 'docx' : 'pdf',
        showMenu: true,
        success: resolve,
        fail: reject,
      })
    })
  },

  // ── Save ──

  async onSave(e) {
    const taskId = Number(e.currentTarget.dataset.id)
    if (!taskId || this.data.savingTaskId) return

    const task = this.data.list.find(item => Number(item.id) === taskId)
    let tempFilePath = ''
    let fileFormat = (task && task.file_format) || 'pdf'
    this.setData({ savingTaskId: taskId })

    try {
      const info = await exportApi.getDownloadInfo(taskId)
      const useAuth = info.method === 'stream'
      const url = useAuth
        ? exportApi.getFileUrl(taskId)
        : (info.url || exportApi.getFileUrl(taskId))
      tempFilePath = await this._downloadFile(url, useAuth)
      fileFormat = (task && task.file_format) ||
        (/\.docx$/i.test(info.file_name || '') ? 'docx' : 'pdf')
      const fileName = this._sanitizeLocalFileName(
        (task && task.file_name) || info.file_name,
        fileFormat
      )
      const savedFilePath = await this._persistDownloadedFile(
        tempFilePath,
        fileName,
        taskId
      )

      wx.showModal({
        title: '保存成功',
        content: '文件已保存到小程序本地。打开文件后，还可以通过右上角菜单发送、收藏或保存到其他应用。',
        confirmText: '打开文件',
        cancelText: '完成',
        success: (res) => {
          if (!res.confirm) return
          this._openSavedDocument(savedFilePath, fileFormat).catch(() => {
            wx.showToast({ title: '打开文件失败', icon: 'none' })
          })
        },
      })
    } catch (err) {
      console.error('Save export failed', err)

      // A device may have its entire mini-program private quota occupied by
      // files outside this page. In that case the downloaded temporary file is
      // still usable: open it with the document menu so the user can save it
      // to WeChat, Files, WPS or another app instead of receiving a dead-end.
      if (tempFilePath && this._isStorageQuotaError(err)) {
        wx.showModal({
          title: '存储空间已满',
          content: '已清理历史导出文件，但小程序私有存储仍不足。可以打开本次文件，通过右上角菜单保存到本地、收藏或发送到其他应用。',
          confirmText: '打开文件',
          cancelText: '暂不打开',
          success: (res) => {
            if (!res.confirm) return
            this._openSavedDocument(tempFilePath, fileFormat).catch(() => {
              wx.showToast({ title: '打开文件失败', icon: 'none' })
            })
          },
        })
        return
      }

      const detail = (err && (err.message || err.errMsg)) || '未知错误'
      wx.showModal({
        title: '保存失败',
        content: '未能保存文件：' + detail,
        showCancel: false,
      })
    } finally {
      if (this._pageAlive) this.setData({ savingTaskId: null })
    }
  },

  // ── Share ──

  /**
   * WeChat share lifecycle method. Triggered by <button open-type="share">.
   * Must return { title, path } — do NOT call wx.shareAppMessage().
   */
  onShareAppMessage(e) {
    const taskId = e.target && e.target.dataset ? e.target.dataset.id : null
    const task = taskId ? this.data.list.find(t => t.id === taskId) : null
    return {
      title: (task && task.file_name) || '错题巩固练习',
      path: '/pages/export-records/export-records' + (task ? '?highlight=' + task.id : ''),
    }
  },

  // ── Delete ──

  onDelete(e) {
    const taskId = e.currentTarget.dataset.id
    const self = this

    wx.showModal({
      title: '确认删除',
      content: '删除后将同时清理文件和导出记录，不可恢复。',
      success: function(res) {
        if (!res.confirm) return
        exportApi.deleteExport(taskId).then(function() {
          // Also stop tracking this task
          if (self._statusSyncManager) {
            self._statusSyncManager.removeTask(taskId)
          }
          self._completedNotified.delete(taskId)
          self.setData({
            list: self.data.list.filter(function(t) { return t.id !== taskId }),
            expandedActionId: self.data.expandedActionId === taskId
              ? null
              : self.data.expandedActionId,
          })
          wx.showToast({ title: '已删除', icon: 'success' })
        }).catch(function() {
          wx.showToast({ title: '删除失败', icon: 'none' })
        })
      },
    })
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

    this.setData({ reExportingTaskId: taskId })
    try {
      const newTask = await exportApi.reExport(taskId)
      if (!newTask || !newTask.id || Number(newTask.id) === taskId) {
        throw new Error('服务端未创建新的导出任务')
      }

      // The endpoint creates a fresh pending task. Show that task immediately
      // instead of reporting a misleading "export succeeded" state.
      this._upsertTaskAtTop({
        ...newTask,
        status: newTask.status || 'pending',
      })
      wx.showToast({ title: '已提交，正在导出', icon: 'none' })
    } catch (err) {
      wx.showToast({ title: err.message || '重新导出失败', icon: 'none' })
    } finally {
      if (this._pageAlive) this.setData({ reExportingTaskId: null })
    }
  },
})

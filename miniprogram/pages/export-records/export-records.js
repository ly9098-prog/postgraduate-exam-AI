/**
 * Export records page — list, poll, preview, save, share, delete, retry, re-export.
 */
const exportApi = require('../../services/export')
const api = require('../../utils/api')

const STATUS_MAP = {
  pending: { label: '等待中', tone: 'neutral' },
  processing: { label: '生成中…', tone: 'info' },
  completed: { label: '已完成', tone: 'success' },
  failed: { label: '失败', tone: 'danger' },
  expired: { label: '已过期', tone: 'muted' },
}

const FORMAT_MAP = {
  pdf: 'PDF',
  docx: 'Word',
}

Page({
  data: {
    list: [],
    page: 1,
    hasMore: false,
    loading: false,

    // Polling
    _pollingTasks: {}, // taskId -> stop function
    _alive: true,
  },

  onLoad(options) {
    this.setData({ _alive: true })
    if (options.highlight) {
      this.setData({ highlightId: parseInt(options.highlight, 10) })
    }
    this._loadList(true)
  },

  onShow() {
    this.setData({ _alive: true })
    // Resume polling for non-terminal tasks
    this._resumePolling()
  },

  onHide() {
    this.setData({ _alive: false })
    this._stopAllPolling()
  },

  onUnload() {
    this.setData({ _alive: false })
    this._stopAllPolling()
  },

  async _loadList(reset = false) {
    if (this.data.loading) return
    this.setData({ loading: true })

    const page = reset ? 1 : this.data.page + 1
    try {
      const res = await exportApi.listExports(page, 20)
      const tasks = res.items || []
      // Precompute display values for WXML
      const enriched = tasks.map(t => this._enrichTask(t))
      const list = reset ? enriched : [...this.data.list, ...enriched]

      this.setData({
        list,
        page: res.page || page,
        hasMore: tasks.length === 20,
        loading: false,
      })

      // Start polling for non-terminal tasks
      enriched.forEach(t => this._startPollingIfNeeded(t))
    } catch (err) {
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
    }
  },

  _enrichTask(task) {
    const st = STATUS_MAP[task.status] || { label: task.status, tone: 'neutral' }
    var fsText = ''
    if (task.file_size) {
      var kb = (task.file_size / 1024)
      fsText = kb.toFixed(1) + 'KB'
    }
    var fmtText = FORMAT_MAP[task.file_format] || task.file_format
    var dateText = task.created_at || ''
    return {
      ...task,
      statusLabel: st.label,
      statusTone: st.tone,
      fileSizeText: fsText,
      formatText: fmtText,
      dateText: dateText,
    }
  },

  onLoadMore() {
    if (!this.data.hasMore || this.data.loading) return
    this._loadList(false)
  },

  // ── Status sync: WebSocket + polling fallback ──
  _startPollingIfNeeded(task) {
    const terminalStates = ['completed', 'failed', 'expired']
    if (terminalStates.includes(task.status)) return
    if (this.data._pollingTasks[task.id]) return

    const stop = exportApi.syncTaskStatus(
      task.id,
      (updated) => {
        if (!this.data._alive) return
        // WS events may have different key naming than API responses
        const taskUpdate = updated.task_id ? {
          id: updated.task_id,
          status: updated.status,
          file_format: updated.file_format,
          success_count: updated.success_count,
          skip_count: updated.skip_count,
          error_message: updated.error_message,
          completed_at: updated.completed_at,
          expires_at: updated.expires_at,
        } : updated

        const enriched = this._enrichTask(taskUpdate || updated)

        this._updateTaskInList(enriched)
        const s = this.data._pollingTasks[task.id]
        // If reached terminal state, stop
        if (s && terminalStates.includes((enriched).status)) {
          s()
          delete this.data._pollingTasks[task.id]
        }
      },
      (err) => {
        // Error — sync service handles internally
      },
      { pollIntervalMs: 3000 },
    )
    this.data._pollingTasks[task.id] = stop
  },

  _resumePolling() {
    this.data.list.forEach(t => this._startPollingIfNeeded(t))
  },

  _stopAllPolling() {
    Object.values(this.data._pollingTasks).forEach(stop => stop())
    this.data._pollingTasks = {}
  },

  _updateTaskInList(updated) {
    const list = this.data.list.map(t =>
      t.id === updated.id ? { ...t, ...updated } : t
    )
    this.setData({ list })
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
          if (res.statusCode === 200) resolve(res.tempFilePath)
          else reject(new Error('下载失败: ' + res.statusCode))
        },
        fail: reject,
      })
    })
  },

  // ── Save ──
  onSave: function(e) {
    var taskId = e.currentTarget.dataset.id
    var self = this
    wx.showToast({ title: '正在保存…', icon: 'loading' })

    exportApi.getDownloadInfo(taskId).then(function(info) {
      var isStream = info.method === 'stream'
      var url = isStream ? exportApi.getFileUrl(taskId) : (info.url || exportApi.getFileUrl(taskId))
      var task = self.data.list.find(function(t) { return t.id === taskId })
      return self._downloadFile(url, isStream).then(function(dl) {
        var fileName = (task && task.file_name) || info.file_name || 'export.' + ((task && task.file_format) || 'pdf')
        var savedPath = wx.env.USER_DATA_PATH + '/' + fileName
        var fs = wx.getFileSystemManager()
        fs.saveFile({
          tempFilePath: dl,
          filePath: savedPath,
          success: function() {
            wx.showToast({ title: '已保存到本地', icon: 'success' })
          },
          fail: function() {
            wx.showToast({ title: '保存失败', icon: 'none' })
          },
        })
      })
    }).catch(function(err) {
      wx.showToast({ title: '保存失败: ' + (err.message || ''), icon: 'none' })
    })
  },

  // ── Share ──
  onShare(e) {
    const task = this._findTaskById(e)
    if (!task) return
    wx.shareAppMessage({
      title: task.file_name || '错题巩固练习',
      path: '/pages/export-records/export-records?highlight=' + task.id,
    })
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
          self.setData({
            list: self.data.list.filter(function(t) { return t.id !== taskId }),
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
  onReExport(e) {
    const taskId = e.currentTarget.dataset.id
    const self = this
    exportApi.reExport(taskId).then(function() {
      wx.showToast({ title: '已重新导出', icon: 'success' })
      self._loadList(true)
    }).catch(function(err) {
      wx.showToast({ title: err.message || '重新导出失败', icon: 'none' })
    })
  },

  _findTaskById(e) {
    const taskId = e.currentTarget.dataset.id
    return this.data.list.find(function(t) { return t.id === taskId })
  },
})

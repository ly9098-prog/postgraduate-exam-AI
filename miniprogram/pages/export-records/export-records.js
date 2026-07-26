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

Page({
  data: {
    list: [],
    page: 1,
    hasMore: false,
    loading: false,
    highlightId: null,

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
      const list = reset ? tasks : [...this.data.list, ...tasks]

      this.setData({
        list,
        page: res.page || page,
        hasMore: tasks.length === 20,
        loading: false,
      })

      // Start polling for non-terminal tasks
      tasks.forEach(t => this._startPollingIfNeeded(t))
    } catch (err) {
      this.setData({ loading: false })
      wx.showToast({ title: '加载失败', icon: 'none' })
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
        // Ensure we process the update correctly — WS events may have
        // different key naming than API responses
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

        this._updateTaskInList(taskUpdate || updated)
        const s = this.data._pollingTasks[task.id]
        // If reached terminal state, stop
        if (s && terminalStates.includes((taskUpdate || updated).status)) {
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

  // ── Task status helper ──
  _taskStatus(task) {
    return STATUS_MAP[task.status] || { label: task.status, tone: 'neutral' }
  },

  // ── Preview (wx.openDocument) ──
  async onPreview(e) {
    const taskId = e.currentTarget.dataset.id
    const task = this.data.list.find(t => t.id === taskId)
    if (!taskId) return

    try {
      const info = await exportApi.getDownloadInfo(taskId)

      let filePath = ''
      if (info.method === 'stream') {
        const url = exportApi.getFileUrl(taskId)
        const dl = await this._downloadFile(url)
        filePath = dl
      } else if (info.url) {
        const dl = await this._downloadFile(info.url)
        filePath = dl
      } else {
        wx.showToast({ title: '无法获取文件', icon: 'none' })
        return
      }

      // Determine file type from task format or file extension
      const fileFormat = (task && task.file_format) || 'pdf'
      const fileType = fileFormat === 'docx' ? 'docx' : 'pdf'

      wx.openDocument({
        filePath,
        fileType: fileType,
        success: () => console.log('Preview success'),
        fail: (err) => {
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

  _downloadFile(url) {
    const token = wx.getStorageSync('token')
    const header = token ? { Authorization: 'Bearer ' + token } : {}
    return new Promise((resolve, reject) => {
      wx.downloadFile({
        url,
        header,
        success: (res) => {
          if (res.statusCode === 200) resolve(res.tempFilePath)
          else reject(new Error('下载失败: ' + res.statusCode))
        },
        fail: reject,
      })
    })
  },

  // ── Save ──
  async onSave(e) {
    const taskId = e.currentTarget.dataset.id
    const task = this.data.list.find(t => t.id === taskId)
    wx.showToast({ title: '正在保存…', icon: 'loading' })

    try {
      const info = await exportApi.getDownloadInfo(taskId)
      const url = info.url || exportApi.getFileUrl(taskId)

      const dl = await this._downloadFile(url)
      const fs = wx.getFileSystemManager()

      // Use the original file name from the task
      const fileName = (task && task.file_name) || (info.file_name) || 'export.' + ((task && task.file_format) || 'pdf')
      const savedPath = `${wx.env.USER_DATA_PATH}/${fileName}`
      fs.saveFile({
        tempFilePath: dl,
        filePath: savedPath,
        success: () => {
          wx.showToast({ title: '已保存到本地', icon: 'success' })
        },
        fail: () => {
          wx.showToast({ title: '保存失败', icon: 'none' })
        },
      })
    } catch (err) {
      wx.showToast({ title: '保存失败: ' + (err.message || ''), icon: 'none' })
    }
  },

  // ── Share ──
  onShare(e) {
    const taskId = e.currentTarget.dataset.id
    const task = this.data.list.find(t => t.id === taskId)
    if (!task) return

    // Share a page where the recipient can view/access the file
    wx.shareAppMessage({
      title: task.file_name || '错题巩固练习',
      path: `/pages/export-records/export-records?highlight=${taskId}`,
    })
  },

  // ── Delete ──
  async onDelete(e) {
    const taskId = e.currentTarget.dataset.id

    wx.showModal({
      title: '确认删除',
      content: '删除后将同时清理文件和导出记录，不可恢复。',
      success: async (res) => {
        if (!res.confirm) return
        try {
          await exportApi.deleteExport(taskId)
          this.setData({
            list: this.data.list.filter(t => t.id !== taskId),
          })
          wx.showToast({ title: '已删除', icon: 'success' })
        } catch (err) {
          wx.showToast({ title: '删除失败', icon: 'none' })
        }
      },
    })
  },

  // ── Retry ──
  async onRetry(e) {
    const taskId = e.currentTarget.dataset.id
    try {
      await exportApi.retryExport(taskId)
      wx.showToast({ title: '已重新提交', icon: 'success' })
      this._loadList(true)
    } catch (err) {
      wx.showToast({ title: err.message || '重试失败', icon: 'none' })
    }
  },

  // ── Re-export ──
  async onReExport(e) {
    const taskId = e.currentTarget.dataset.id
    try {
      await exportApi.reExport(taskId)
      wx.showToast({ title: '已重新导出', icon: 'success' })
      this._loadList(true)
    } catch (err) {
      wx.showToast({ title: err.message || '重新导出失败', icon: 'none' })
    }
  },
})

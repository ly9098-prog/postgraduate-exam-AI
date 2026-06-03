const api = require('../../utils/api')
const auth = require('../../utils/auth')
const config = require('../../config')

const SUPPORTED_EXTENSIONS = ['xlsx', 'xls', 'pdf', 'txt', 'jpg', 'jpeg', 'png', 'webp']
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']

function getExtension(name) {
  if (!name) return ''
  const parts = name.split('.')
  return parts.length > 1 ? parts.pop().toLowerCase() : ''
}

Page({
  data: {
    batches: [],
    loading: false,
    error: '',
    pipelineTask: null,
    pipelinePolling: false,
  },

  onLoad() {
    if (!auth.requireAdminAccess()) {
      wx.redirectTo({ url: '/pages/home/home' })
    }
  },

  onShow() {
    try {
      if (!auth.isAdmin()) return
      this.loadBatches()
    } catch (e) {
      console.error('import page onShow error:', e)
    }
  },

  onUnload() {
    if (this.pollTimer) clearTimeout(this.pollTimer)
  },

  onHide() {
    if (this.pollTimer) clearTimeout(this.pollTimer)
  },

  async loadBatches() {
    this.setData({ loading: true, error: '' })
    try {
      const res = await api.get('/import/batches')
      const items = (res && res.items) ? res.items : []
      this.setData({
        batches: items.map(b => ({
          ...b,
          _date: b.created_at ? b.created_at.slice(0, 16) : '',
        })),
      })
    } catch (e) {
      console.error('加载批次列表失败', e)
      this.setData({ error: '加载失败，下拉重试' })
    } finally {
      this.setData({ loading: false })
    }
  },

  onPullDownRefresh() {
    this.loadBatches().then(() => wx.stopPullDownRefresh())
  },

  chooseFile() {
    wx.showActionSheet({
      itemList: ['从聊天记录选文件', '拍照/相册选图片'],
      success: (res) => {
        if (res.tapIndex === 0) {
          this.pickFromMessage()
        } else if (res.tapIndex === 1) {
          this.pickImage()
        }
      },
    })
  },

  pickFromMessage() {
    if (!wx.chooseMessageFile) {
      wx.showModal({
        title: '提示',
        content: '当前微信版本不支持文件选择，请升级微信',
        showCancel: false,
      })
      return
    }
    wx.chooseMessageFile({
      count: 1,
      type: 'all',
      success: (res) => {
        const file = res.tempFiles[0]
        if (!file) return
        const name = (file.name || '').toLowerCase()
        const ext = getExtension(name)
        if (!SUPPORTED_EXTENSIONS.includes(ext)) {
          wx.showToast({ title: '不支持该格式，仅支持 xlsx/pdf/txt/jpg/png/webp', icon: 'none' })
          return
        }
        this.unifiedUpload(file.path, file.name || name)
      },
      fail: (err) => {
        if (err && err.errMsg && err.errMsg.includes('cancel')) return
        wx.showToast({ title: '选择文件失败', icon: 'none' })
      },
    })
  },

  pickImage() {
    if (wx.chooseMedia) {
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album', 'camera'],
        success: (res) => {
          const file = res.tempFiles && res.tempFiles[0]
          if (!file) return
          this.unifiedUpload(file.tempFilePath, 'photo.jpg')
        },
        fail: (err) => {
          if (err && err.errMsg && err.errMsg.includes('cancel')) return
          wx.showToast({ title: '选择图片失败', icon: 'none' })
        },
      })
      return
    }
    if (!wx.chooseMessageFile) {
      wx.showModal({
        title: '提示',
        content: '当前微信版本不支持图片选择，请升级微信',
        showCancel: false,
      })
      return
    }
    wx.chooseMessageFile({
      count: 1,
      type: 'image',
      success: (res) => {
        const file = res.tempFiles[0]
        if (!file) return
        this.unifiedUpload(file.path, file.name || 'image.jpg')
      },
      fail: (err) => {
        if (err && err.errMsg && err.errMsg.includes('cancel')) return
        wx.showToast({ title: '选择图片失败', icon: 'none' })
      },
    })
  },

  async unifiedUpload(path, name) {
    wx.showLoading({ title: '上传中...' })
    try {
      const token = wx.getStorageSync('token')
      const res = await new Promise((resolve, reject) => {
        wx.uploadFile({
          url: `${config.BASE_URL}/import/pipeline/upload`,
          filePath: path,
          name: 'file',
          header: { Authorization: `Bearer ${token}` },
          success: (r) => {
            let body = null
            try {
              body = JSON.parse(r.data)
            } catch (e) {
              return reject(new Error(`服务器返回异常 (HTTP ${r.statusCode})`))
            }
            if (r.statusCode >= 400) {
              return reject(new Error(body.detail || body.message || `HTTP ${r.statusCode}`))
            }
            resolve(body)
          },
          fail: reject,
        })
      })
      wx.hideLoading()
      this.setData({
        pipelineTask: {
          pipeline_id: res.pipeline_id,
          status: res.status || 'parsing',
          source_type: res.source_type || '',
          raw_text_preview: '',
          errors: [],
          error_message: '',
          source_file: name,
        },
        pipelinePolling: true,
      })
      this.pollPipeline(res.pipeline_id)
    } catch (err) {
      wx.hideLoading()
      wx.showModal({
        title: '上传失败',
        content: err.message || '未知错误',
        showCancel: false,
      })
    }
  },

  async pollPipeline(pipelineId) {
    if (!pipelineId) return
    if (this.pollTimer) clearTimeout(this.pollTimer)
    try {
      const status = await api.get(`/import/pipelines/${pipelineId}`)
      this._pollRetries = 0
      const currentTask = this.data.pipelineTask || {}
      if (currentTask.pipeline_id !== pipelineId) return
      const errors = status.errors || []
      const task = {
        ...currentTask,
        ...status,
        errors,
        error_message: errors[0] || '',
        raw_text_preview: (status.raw_text_preview || '').slice(0, 200),
        question_count: status.question_count || (status.stats && status.stats.to_review) || 0,
      }
      this.setData({ pipelineTask: task, pipelinePolling: !['completed', 'failed'].includes(task.status) })
      if (task.status === 'completed') {
        wx.showToast({ title: `已导入 ${task.question_count || 0} 题，进入审核`, icon: 'none' })
        this.loadBatches()
        return
      }
      if (task.status === 'failed') {
        wx.showModal({
          title: '导入失败',
          content: task.error_message || '解析失败',
          showCancel: false,
        })
        return
      }
      this.pollTimer = setTimeout(() => this.pollPipeline(pipelineId), 2000)
    } catch (e) {
      console.error('查询导入状态失败', e)
      const retries = (this._pollRetries || 0) + 1
      if (retries < 3) {
        this._pollRetries = retries
        this.pollTimer = setTimeout(() => this.pollPipeline(pipelineId), 3000)
      } else {
        this._pollRetries = 0
        this.setData({ pipelinePolling: false })
      }
    }
  },

  goBatch(e) {
    const batchId = e.currentTarget.dataset.batchId
    if (!batchId) return
    wx.navigateTo({ url: `/pages/import-batch/import-batch?batchId=${batchId}` })
  },

  async downloadTemplate() {
    wx.showLoading({ title: '下载模板中...' })
    try {
      const token = wx.getStorageSync('token')
      const res = await new Promise((resolve, reject) => {
        wx.downloadFile({
          url: `${config.BASE_URL}/import/template`,
          header: { Authorization: `Bearer ${token}` },
          success: resolve,
          fail: reject,
        })
      })
      if (res.statusCode !== 200) throw new Error('下载失败')
      await wx.openDocument({ filePath: res.tempFilePath, fileType: 'xlsx' })
      wx.hideLoading()
    } catch (err) {
      wx.hideLoading()
      wx.showToast({ title: '下载失败', icon: 'none' })
    }
  },

  subjectLabel(s) {
    const map = { math2: '数学二', exam408: '408', english: '英语' }
    return map[s] || s || '-'
  },
})

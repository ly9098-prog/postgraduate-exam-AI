const api = require('../../utils/api')
const auth = require('../../utils/auth')
const config = require('../../config')

Page({
  data: {
    batches: [],
    loading: false,
    error: '',
    imageTask: null,
    imagePolling: false,
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
    if (this.imagePollTimer) clearTimeout(this.imagePollTimer)
  },

  onHide() {
    if (this.imagePollTimer) clearTimeout(this.imagePollTimer)
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
    // 检查 API 可用性
    if (!wx.chooseMessageFile) {
      wx.showModal({
        title: '提示',
        content: '当前微信版本不支持文件选择，请升级微信或使用其他方式导入',
        showCancel: false,
      })
      return
    }
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['xlsx', 'xls', 'pdf'],
      success: (res) => {
        const file = res.tempFiles[0]
        if (!file) return
        const name = (file.name || '').toLowerCase()
        if (!name.endsWith('.xlsx') && !name.endsWith('.xls') && !name.endsWith('.pdf')) {
          wx.showToast({ title: '仅支持 .xlsx / .pdf 文件', icon: 'none' })
          return
        }
        this.uploadFile(file.path, name)
      },
      fail: (err) => {
        if (err && err.errMsg && err.errMsg.includes('cancel')) return
        wx.showToast({ title: '选择文件失败', icon: 'none' })
      },
    })
  },

  chooseImage() {
    if (wx.chooseMedia) {
      wx.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sourceType: ['album', 'camera'],
        success: (res) => {
          const file = res.tempFiles && res.tempFiles[0]
          if (!file) return
          this.uploadImage(file.tempFilePath, 'image.jpg')
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
        content: '当前微信版本不支持图片文件选择，请升级微信后重试',
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
        const rawName = file.name || file.path || 'image.jpg'
        const name = rawName.toLowerCase()
        if (!name.endsWith('.jpg') && !name.endsWith('.jpeg') && !name.endsWith('.png') && !name.endsWith('.webp')) {
          wx.showToast({ title: '仅支持 jpg/png/webp 图片', icon: 'none' })
          return
        }
        this.uploadImage(file.path, name)
      },
      fail: (err) => {
        if (err && err.errMsg && err.errMsg.includes('cancel')) return
        wx.showToast({ title: '选择图片失败', icon: 'none' })
      },
    })
  },

  async uploadImage(path, name) {
    wx.showLoading({ title: '图片上传中...' })
    try {
      const token = wx.getStorageSync('token')
      const res = await new Promise((resolve, reject) => {
        wx.uploadFile({
          url: `${config.BASE_URL}/import/image/upload`,
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
        imageTask: {
          pipeline_id: res.pipeline_id,
          status: res.status || 'queued',
          raw_text_preview: '',
          errors: [],
          error_message: '',
        },
        imagePolling: true,
      })
      this.pollImagePipeline(res.pipeline_id)
    } catch (err) {
      wx.hideLoading()
      wx.showModal({
        title: '图片上传失败',
        content: err.message || '未知错误',
        showCancel: false,
      })
    }
  },

  async pollImagePipeline(pipelineId) {
    if (!pipelineId) return
    if (this.imagePollTimer) clearTimeout(this.imagePollTimer)
    try {
      const status = await api.get(`/import/pipelines/${pipelineId}`)
      const currentTask = this.data.imageTask || {}
      if (currentTask.pipeline_id !== pipelineId) return
      const errors = status.errors || []
      const task = {
        ...status,
        errors,
        error_message: errors[0] || '',
        raw_text_preview: (status.raw_text_preview || '').slice(0, 200),
        question_count: status.question_count || (status.stats && status.stats.to_review) || 0,
      }
      this.setData({ imageTask: task, imagePolling: !['completed', 'failed'].includes(task.status) })
      if (task.status === 'completed') {
        wx.showToast({ title: `已进入审核 ${task.question_count || 0} 题`, icon: 'none' })
        this.loadBatches()
        return
      }
      if (task.status === 'failed') {
        wx.showModal({
          title: '图片解析失败',
          content: task.error_message || 'OCR 或解析失败',
          showCancel: false,
        })
        return
      }
      this.imagePollTimer = setTimeout(() => this.pollImagePipeline(pipelineId), 2000)
    } catch (e) {
      console.error('查询图片导入状态失败', e)
      this.setData({ imagePolling: false })
    }
  },

  async uploadFile(path, name) {
    wx.showLoading({ title: '上传解析中...' })
    try {
      const token = wx.getStorageSync('token')
      const res = await new Promise((resolve, reject) => {
        wx.uploadFile({
          url: `${config.BASE_URL}/import/upload`,
          filePath: path,
          name: 'file',
          header: { Authorization: `Bearer ${token}` },
          success: (r) => {
            let body = null
            try {
              body = JSON.parse(r.data)
            } catch (e) {
              console.error('解析上传响应失败', e, 'status=', r.statusCode)
              const preview = String(r.data || '').slice(0, 120)
              return reject(new Error(`服务器返回异常 (HTTP ${r.statusCode})：${preview}`))
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
      wx.showToast({ title: `导入 ${res.total || 0} 道题成功`, icon: 'none' })
      this.loadBatches()
    } catch (err) {
      wx.hideLoading()
      wx.showModal({
        title: '上传失败',
        content: err.message || '未知错误',
        showCancel: false,
      })
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

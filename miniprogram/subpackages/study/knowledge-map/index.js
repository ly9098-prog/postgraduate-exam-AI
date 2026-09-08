const api = require('../../../utils/api')


function subjectMark(name, code) {
  const text = `${String(name || '')} ${String(code || '')}`.toLowerCase()
  if (text.includes('数据结构') || text.includes('data_structure')) return '数'
  if (text.includes('组成') || text.includes('organization')) return '组'
  if (text.includes('操作系统') || text.includes('operating')) return '系'
  if (text.includes('网络') || text.includes('network')) return '网'
  if (text.includes('高等数学') || text.includes('calculus')) return '高'
  if (text.includes('线性代数') || text.includes('linear')) return '线'
  if (text.includes('英语') || text.includes('english')) return '英'
  if (text.includes('政治') || text.includes('politic')) return '政'
  const clean = String(name || '').trim()
  return clean ? clean.slice(0, 1) : '科'
}

function subjectIconClass(name, code) {
  const text = `${String(name || '')} ${String(code || '')}`.toLowerCase()
  if (text.includes('数据结构') || text.includes('data_structure')) return 'data'
  if (text.includes('组成') || text.includes('organization')) return 'chip'
  if (text.includes('操作系统') || text.includes('operating')) return 'code'
  if (text.includes('网络') || text.includes('network')) return 'network'
  if (text.includes('高等数学') || text.includes('calculus')) return 'math'
  if (text.includes('线性代数') || text.includes('linear')) return 'matrix'
  if (text.includes('英语') || text.includes('english')) return 'language'
  if (text.includes('政治') || text.includes('politic')) return 'civic'
  return 'generic'
}


function subjectIconPath(iconClass) {
  const icons = {
    data: '/assets/icons/knowledge-map/data-structure.png',
    chip: '/assets/icons/knowledge-map/computer-organization.png',
    network: '/assets/icons/knowledge-map/computer-network.png',
    code: '/assets/icons/knowledge-map/operating-system.png',
  }
  return icons[iconClass] || '/assets/icons/knowledge-map/data-structure.png'
}

const STATUS_META = {
  no_data: { text: '未开始', hint: '完成相关练习后生成掌握度' },
  insufficient: { text: '数据不足', hint: '继续练习，达到可靠样本后展示' },
  weak: { text: '薄弱', hint: '建议优先专项强化' },
  developing: { text: '提升中', hint: '掌握度正在建立' },
  good: { text: '良好', hint: '保持复习与巩固' },
  mastered: { text: '已掌握', hint: '注意周期复习防止遗忘' },
}

Page({
  data: {
    loading: true,
    error: '',
    scopeReady: true,
    syllabusVersion: null,
    subjects: [],
    observedTotal: 0,
    weakTotal: 0,
  },

  onLoad() {
    this.loadOverview()
  },

  onPullDownRefresh() {
    this.loadOverview().finally(() => wx.stopPullDownRefresh())
  },

  async loadOverview() {
    this.setData({ loading: true, error: '' })
    try {
      const data = await api.get('/knowledge-map/overview')
      const subjectPriority = item => {
        const key = `${String(item && item.subject_name || '')} ${String(item && item.subject_code || '')}`.toLowerCase()
        if (key.includes('数据结构') || key.includes('data_structure')) return 10
        if (key.includes('组成') || key.includes('organization')) return 20
        if (key.includes('网络') || key.includes('network')) return 30
        if (key.includes('操作系统') || key.includes('operating')) return 40
        return 100
      }
      const rawSubjects = Array.isArray(data.subjects) ? data.subjects.slice() : []
      rawSubjects.sort((a, b) => subjectPriority(a) - subjectPriority(b))
      const subjects = rawSubjects.map((item, index) => {
        const meta = STATUS_META[item.status] || STATUS_META.no_data
        const score = item.mastery_score == null ? null : Math.max(0, Math.min(100, Math.round(Number(item.mastery_score) || 0)))
        const coverage = Math.max(0, Math.min(100, Math.round((Number(item.coverage_ratio) || 0) * 100)))
        const reliable = Number(item.reliable_knowledge_points) || 0
        const trainable = Number(item.trainable_knowledge_points) || 0
        return {
          ...item,
          orderText: String(index + 1).padStart(2, '0'),
          mark: subjectMark(item.subject_name, item.subject_code),
          iconClass: subjectIconClass(item.subject_name, item.subject_code),
          iconPath: subjectIconPath(subjectIconClass(item.subject_name, item.subject_code)),
          score,
          scoreText: score == null ? '0%' : `${score}%`,
          barWidth: score == null ? 0 : score,
          coverage,
          statusText: meta.text,
          statusHint: meta.hint,
          statusClass: `status-${item.status || 'no_data'}`,
          reliableCount: reliable,
          trainableCount: trainable,
          progressText: `${reliable}/${trainable} 个知识点`,
        }
      })
      this.setData({
        loading: false,
        scopeReady: data.scope_ready !== false,
        syllabusVersion: data.syllabus_version || null,
        subjects,
        observedTotal: subjects.reduce((sum, item) => sum + (Number(item.observed_knowledge_points) || 0), 0),
        weakTotal: subjects.reduce((sum, item) => sum + (Number(item.weak_knowledge_points) || 0), 0),
      })
    } catch (error) {
      this.setData({ loading: false, error: api.getErrorMessage(error) })
    }
  },

  openSubject(event) {
    const subjectId = Number(event.currentTarget.dataset.subjectId)
    if (!subjectId) return
    wx.navigateTo({ url: `/subpackages/study/knowledge-subject/index?subject_id=${subjectId}` })
  },

  retry() {
    this.loadOverview()
  },
})

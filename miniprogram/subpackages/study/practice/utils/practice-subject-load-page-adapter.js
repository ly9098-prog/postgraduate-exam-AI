const {
  createPracticeSubjectLoadController,
} = require('./practice-subject-load-controller')

function createPracticeSubjectLoadPageController(page, dependencies) {
  const { api, filterSubjectTree, normalizeSubjectTree } = dependencies

  return createPracticeSubjectLoadController({
    nextRequestSeq: () => ++page._subjectsRequestSeq,
    isCurrent: requestSeq => page._pageAlive && requestSeq === page._subjectsRequestSeq,
    fetchSubjects: async () => {
      if (!page.data.guestMode) return api.get('/practice/subjects')
      page.setData({ subjectsLoadFailed: false, errorText: '' })
      const response = await api.get('/guest/practice/subjects', {}, { auth: 'none' })
      return response && response.items || []
    },
    filterSubjectTree,
    normalizeSubjectTree,
    setData: patch => page.setData(patch),
    getSelectedSubjectId: () => page.data.selectedSubjectId,
    preserveSelectedSubject: subjectTree => {
      const available = page._flattenSelectableSubjects(subjectTree || [])
      const target = available.find(item => (
        Number(item.subject_id) === Number(page.data.selectedSubjectId)
      ))
      if (!target) return
      page.setData({
        selectedSubjectName: page.data.selectedSubjectName || target.display_name,
        selectedSubjectHasChildren: Boolean(target.has_children),
        expandedSubjectId: target.parent_subject_id || target.subject_id,
      })
    },
    initDefaultSubject: subjectTree => page.initDefaultSubject(subjectTree),
    applyLaunchPreset: subjectTree => page._applyLaunchPreset(subjectTree),
    shouldAutostart: () => Boolean(
      page._launchPreset && page._launchPreset.autostart && page._pageAlive,
    ),
    startPractice: () => page.startPractice(),
    logError: (message, error) => console.error(message, error),
    showToast: options => {
      if (page.data.guestMode) {
        page.setData({ subjectsLoadFailed: true, errorText: '加载科目失败，请重试' })
      }
      dependencies.wx.showToast(options)
    },
  })
}

module.exports = {
  createPracticeSubjectLoadPageController,
}

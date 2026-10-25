const {
  RECENT_SUBJECTS_STORAGE_KEY,
  rememberSubject,
} = require('./recent-subjects')

function createRecentSubjectController(options) {
  return {
    remember: (subjectId, subjectName) => remember(options, subjectId, subjectName),
    queue: (subjectId, subjectName) => queue(options, subjectId, subjectName),
    flush: () => flush(options),
  }
}

function remember(options, subjectId, subjectName) {
  const id = Number(subjectId)
  if (!id || !subjectName) return
  const result = rememberSubject({
    subjectId: id,
    subjectName,
    parentSubjectId: options.findParentSubjectId(id),
    hasChildren: options.subjectHasChildren(id),
    currentRecentSubjects: options.getRecentSubjects(),
    decorateRecentSubjects: subjects => options.decorateRecentSubjects(subjects),
  })
  options.setData(result.view)
  try {
    options.setStorage(RECENT_SUBJECTS_STORAGE_KEY, result.storageValue)
  } catch (error) {
    options.logWarn('保存最近使用科目失败', error)
  }
}

function queue(options, subjectId, subjectName) {
  const id = Number(subjectId)
  if (!id || !subjectName) return
  options.setPending({ subjectId: id, subjectName })
}

function flush(options) {
  const pending = options.getPending()
  options.setPending(null)
  if (!pending) return
  remember(options, pending.subjectId, pending.subjectName)
}

module.exports = { createRecentSubjectController }

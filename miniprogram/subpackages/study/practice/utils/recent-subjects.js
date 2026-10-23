const RECENT_SUBJECTS_STORAGE_KEY = 'practice_recent_subjects_v1'

function selectDefaultSubject(options) {
  const availableSubjects = options.flattenSelectableSubjects(options.subjectTree)
  const availableMap = {}
  availableSubjects.forEach((item) => { availableMap[item.subject_id] = item })
  const validStored = options.storedSubjects
    .map(item => availableMap[Number(item.subject_id)])
    .filter(Boolean)
  const fallback = availableSubjects[0]
  const selected = validStored[0] || fallback
  if (!selected) return null
  const recentBase = validStored.length > 0 ? validStored : [selected]
  return {
    view: {
      expandedSubjectId: selected.parent_subject_id || selected.subject_id,
      selectedSubjectId: selected.subject_id,
      selectedSubjectName: selected.display_name,
      selectedSubjectHasChildren: Boolean(selected.has_children),
      recentSubjects: options.decorateRecentSubjects(recentBase.slice(0, 4)),
    },
  }
}

function rememberSubject(options) {
  const base = [{
    subject_id: options.subjectId,
    display_name: options.subjectName,
    parent_subject_id: options.parentSubjectId || options.subjectId,
    has_children: options.hasChildren,
  }].concat(options.currentRecentSubjects.filter(item => Number(item.subject_id) !== options.subjectId))
  const recentSubjects = options.decorateRecentSubjects(base.slice(0, 4))
  return {
    view: { recentSubjects },
    storageValue: recentSubjects.map(item => ({
      subject_id: item.subject_id,
      display_name: item.display_name,
      parent_subject_id: item.parent_subject_id,
    })),
  }
}

module.exports = {
  RECENT_SUBJECTS_STORAGE_KEY,
  selectDefaultSubject,
  rememberSubject,
}

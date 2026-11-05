function createSubjectSelectionController(options) {
  return {
    select: (subjectId, subjectName, expandedSubjectId, hasChildren) => select(options, subjectId, subjectName, expandedSubjectId, hasChildren),
    chooseRecent: event => chooseRecent(options, event),
    chooseParent: event => chooseParent(options, event),
    toggleExpansion: event => toggleExpansion(options, event),
    chooseChild: event => chooseChild(options, event),
    chooseMode: event => chooseMode(options, event),
    setCount: event => setCount(options, event),
  }
}

function dataset(event) {
  return (event && event.currentTarget && event.currentTarget.dataset) || {}
}

function select(options, subjectId, subjectName, expandedSubjectId, hasChildren) {
  const id = Number(subjectId)
  if (!id || !subjectName) return
  if (Number(options.getSelectedSubjectId()) !== id) options.clearLaunchOverrides()
  const resolvedHasChildren = hasChildren != null
    ? Boolean(hasChildren)
    : options.subjectHasChildren(id)
  const patch = {
    selectedSubjectId: id,
    selectedSubjectName: subjectName,
    selectedSubjectHasChildren: resolvedHasChildren,
  }
  if (expandedSubjectId != null) {
    patch.expandedSubjectId = Number(expandedSubjectId)
  } else if (resolvedHasChildren) {
    patch.expandedSubjectId = id
  }
  options.queueRememberSubject(id, subjectName)
  options.setData(patch)
}

function chooseRecent(options, event) {
  const ds = dataset(event)
  const subjectId = Number(ds.subjectId)
  const subjectName = ds.subjectName
  const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
  if (!subjectId || !subjectName) return
  const parentId = options.findParentSubjectId(subjectId)
  select(options, subjectId, subjectName, parentId || subjectId, hasChildren)
  options.handleSubjectOptionTap(subjectId, 'recent')
}

function chooseParent(options, event) {
  const ds = dataset(event)
  const subjectId = Number(ds.subjectId)
  const subjectName = ds.subjectName
  const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
  if (!subjectId || !subjectName) return
  const selectedName = hasChildren ? `${subjectName}（全部）` : subjectName
  select(options, subjectId, selectedName, undefined, hasChildren)
  options.handleSubjectOptionTap(subjectId, 'parent')
}

function toggleExpansion(options, event) {
  const subjectId = Number(dataset(event).subjectId)
  if (!subjectId) return
  const next = options.getExpandedSubjectId() === subjectId ? null : subjectId
  options.setData({ expandedSubjectId: next })
}

function chooseChild(options, event) {
  const ds = dataset(event)
  const subjectId = Number(ds.subjectId)
  const subjectName = ds.subjectName
  const hasChildren = ds.hasChildren === true || ds.hasChildren === 'true'
  if (!subjectId || !subjectName) return
  select(options, subjectId, subjectName, options.findParentSubjectId(subjectId), hasChildren)
  options.handleSubjectOptionTap(subjectId, 'child')
}

function chooseMode(options, event) {
  const mode = dataset(event).mode
  if (options.isGuest && options.isGuest() && mode !== 'random') return
  if (String(options.getSelectedMode() || '') !== String(mode || '')) {
    options.clearLaunchOverrides()
  }
  options.setData({ selectedMode: mode }, options.updateComputedFields)
}

function setCount(options, event) {
  const count = Number(dataset(event).count)
  if (Number(options.getCount()) !== count) {
    options.clearLaunchOverrides()
  }
  options.setData({ count }, options.updateComputedFields)
}

module.exports = { createSubjectSelectionController }

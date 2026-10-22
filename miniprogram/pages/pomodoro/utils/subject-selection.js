function findRouteSubject(options) {
  const routeId = options.route.subjectId
  const routeCode = options.route.subjectCode || ''
  const matchesRoute = subject => (
    routeId
      ? Number(subject.id) === Number(routeId)
      : String(subject.code || '') === String(routeCode)
  )
  const aggregateMatch = options.aggregate &&
    !options.aggregate._disabled &&
    options.coreSubjects.length === 4 &&
    matchesRoute(options.aggregate)
    ? options.aggregate
    : null
  const match = aggregateMatch || options.leaves.find(matchesRoute)
  if (!match) return null
  return {
    selectedSubjectId: match.id,
    selectedSubject: match,
    allocationMode: match._isAggregate ? 'equal_408_core_v1' : 'single',
  }
}

function findLegacySubject(selectedSubject, leaves) {
  if (!selectedSubject || selectedSubject.id || !selectedSubject.code) return null
  const match = (leaves || []).find(subject => subject.code === selectedSubject.code)
  return match
    ? { selectedSubjectId: match.id, selectedSubject: match }
    : null
}

function findSubjectById(subjects, id) {
  const numericId = Number(id)
  if (!numericId) return null
  return (subjects || []).find(subject => Number(subject.id) === numericId) || null
}

module.exports = { findRouteSubject, findLegacySubject, findSubjectById }

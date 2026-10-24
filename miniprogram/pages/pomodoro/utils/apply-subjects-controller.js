/**
 * Apply loaded subjects to the page: set choices, resolve route/legacy selection.
 * Pure planner — caller applies returned patches via setData.
 */
const { normalizeCachedSubjects } = require('./subject-options')
const { findRouteSubject, findLegacySubject } = require('./subject-selection')

function buildApplySubjectsPlan(flat, pageData) {
  const { choices, aggregate, leaves, coreSubjects } = normalizeCachedSubjects(flat)
  const patches = [{
    subjects: choices,
    aggregateAvailable: !!aggregate && coreSubjects.length === 4,
    coreSubjects,
    subjectsLoading: false,
    subjectsError: '',
  }]

  const route = {
    subjectId: pageData.fromSubjectId,
    subjectCode: pageData.fromSubjectCode,
  }
  const routeSelection = (route.subjectId || route.subjectCode)
    ? findRouteSubject({ route, aggregate, leaves, coreSubjects })
    : null
  if (routeSelection) {
    patches.push(routeSelection)
  }

  const legacySelection = findLegacySubject(pageData.selectedSubject, leaves)
  if (legacySelection) {
    patches.push(legacySelection)
  }

  return { patches, leaves }
}

module.exports = { buildApplySubjectsPlan }

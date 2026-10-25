function parseReturnIdentity(options, returnTo) {
  const targetPath = String(returnTo).split('?')[0].replace(/^\//, '')
  if (!targetPath) return null
  let expectedSubjectId = 0
  let expectedPointId = 0
  const query = String(returnTo).split('?')[1] || ''
  query.split('&').forEach((part) => {
    const pair = String(part || '').split('=')
    const key = pair[0]
    const value = Number(options.safeDecodeURIComponent(pair.slice(1).join('='), ''))
    if (key === 'subject_id' && Number.isInteger(value) && value > 0) expectedSubjectId = value
    if (key === 'knowledge_point_id' && Number.isInteger(value) && value > 0) expectedPointId = value
  })
  return { targetPath, expectedSubjectId, expectedPointId }
}

function pageMatchesIdentity(page, identity) {
  if (!page || !identity) return false
  const route = String(page.route || '').replace(/^\//, '')
  if (route !== identity.targetPath) return false
  if (identity.targetPath === 'subpackages/knowledge/knowledge-subject/index' && identity.expectedSubjectId) {
    const pageSubjectId = Number(page.subjectId || (page.options && page.options.subject_id)) || 0
    return !pageSubjectId || pageSubjectId === identity.expectedSubjectId
  }
  if (identity.targetPath === 'subpackages/knowledge/knowledge-detail/index' && identity.expectedPointId) {
    const currentPointId = Number(page.knowledgePointId || (page.options && page.options.knowledge_point_id)) || 0
    return !currentPointId || currentPointId === identity.expectedPointId
  }
  return true
}

function nearestMatchingIndex(pages, identity) {
  let nearest = -1
  for (let i = pages.length - 2; i >= 0; i -= 1) {
    if (pageMatchesIdentity(pages[i], identity)) {
      nearest = i
      break
    }
  }
  return nearest
}

function oldestMatchingIndex(pages, identity, nearest) {
  let targetIndex = nearest
  for (let i = nearest - 1; i >= 0; i -= 1) {
    if (!pageMatchesIdentity(pages[i], identity)) break
    targetIndex = i
  }
  return targetIndex
}

module.exports = {
  parseReturnIdentity,
  pageMatchesIdentity,
  nearestMatchingIndex,
  oldestMatchingIndex,
}

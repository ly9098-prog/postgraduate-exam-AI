/**
 * Pure helpers for exam paper list search and rendering,
 * extracted from paper-list/index.js.
 */

function normalizeSearchValue(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/408/g, '')
    .replace(/[\s\-_\/.,，。:：;；|｜()[\]{}【】（）'"""''·]+/g, '')
}

function fuzzyIncludes(target, term) {
  if (!term) return true
  if (target.indexOf(term) !== -1) return true
  var termIndex = 0
  for (var i = 0; i < target.length && termIndex < term.length; i += 1) {
    if (target[i] === term[termIndex]) termIndex += 1
  }
  return termIndex === term.length
}

function matchesPaper(paper, query) {
  var rawTerms = String(query || '').trim().split(/\s+/).filter(Boolean)
  if (!rawTerms.length) return true
  var target = normalizeSearchValue([
    paper.title,
    paper.source,
    paper.typeLabel,
    paper.typeHint,
    paper.year,
    paper.question_count ? paper.question_count + '题' : '',
    paper.scoreText ? paper.scoreText + '分' : '',
    paper.durationMinutes ? paper.durationMinutes + '分钟' : '',
  ].join(' '))
  return rawTerms.every(function(rawTerm) { return fuzzyIncludes(target, normalizeSearchValue(rawTerm)) })
}

function paperRenderSignature(papers) {
  return (Array.isArray(papers) ? papers : []).map(function(item) {
    return [
      item.id,
      item.title,
      item.source,
      item.typeLabel,
      item.year,
      item.question_count,
      item.scoreText,
      item.durationMinutes,
      item.bestScoreText,
      item.canResume ? 1 : 0,
      item.latest_attempt_id || '',
      item.isSuggested ? 1 : 0,
      item.isLatestYear ? 1 : 0,
    ].join('|')
  }).join('||')
}

module.exports = { normalizeSearchValue, fuzzyIncludes, matchesPaper, paperRenderSignature }

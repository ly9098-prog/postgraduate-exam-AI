/**
 * Build a recovery question list from the full question objects.
 *
 * Pure function — extracted from practice.js doSubmit to make the
 * recovery snapshot contract testable without a page instance.
 * Only carries fields needed for result-page recovery.
 */
function buildRecoveryQuestions(questions) {
  return (questions || []).map(function(q) {
    var stem = (q && q.content && (q.content.text || q.content.stem)) || (q && q.stem) || ''
    return {
      id: q && q.id,
      question_version_id: q && q.question_version_id,
      question_version: q && q.question_version,
      subject_id: q && q.subject_id,
      subject_code: (q && q.subject_code) || '',
      subject_name: (q && q.subject_name) || '',
      question_type: (q && q.question_type) || '',
      content: (q && q.content) || {},
      options: (q && q.options) || null,
      image_url: (q && q.image_url) || null,
      knowledge_points: (q && q.knowledge_points) || [],
      difficulty: (q && q.difficulty) || 3,
      stem: String(stem || ''),
    }
  }).filter(function(q) { return !!q.id })
}

module.exports = { buildRecoveryQuestions }

const { studyStrategy } = require('../../utils/storage')

// IDs come from the active practice catalog, including subjects without attempts.
function buildDiagnosisSubjectOptions(raw) {
  const nodes = Array.isArray(raw) ? raw : (raw && Array.isArray(raw.items) ? raw.items : [])
  const byCode = new Map()
  function visit(node) {
    if (!node || node.is_active === false) return
    const code = String(node.subject_code || node.code || '')
    const id = Number(node.subject_id == null ? node.id : node.subject_id)
    if (Number.isInteger(id) && id > 0 && !byCode.has(code)) byCode.set(code, { node, id })
    if (Array.isArray(node.children)) node.children.forEach(visit)
  }
  nodes.forEach(visit)
  return studyStrategy.SUBJECTS.filter(meta => byCode.has(meta.code)).map(meta => {
    const { node, id } = byCode.get(meta.code)
    return {
      subjectId: id,
      code: meta.code,
      label: meta.shortName,
      name: String(node.subject_name || node.display_name || node.name || meta.name),
    }
  })
}

module.exports = { buildDiagnosisSubjectOptions }

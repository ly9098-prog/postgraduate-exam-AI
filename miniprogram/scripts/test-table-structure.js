const assert = require('assert')
const table = require('../subpackages/study/utils/table-structure')
const stemRender = require('../subpackages/study/utils/stem-render')

const structured = table.normalizeTableSegment({
  type: 'table',
  schema_version: 'table.v2',
  confidence: 0.92,
  rows: [
    { cells: [
      { text: '进程', is_header: true, row_span: 2 },
      { text: '时间', is_header: true, col_span: 2 },
    ] },
    { cells: [
      { text: '到达', is_header: true },
      { text: '服务', is_header: true },
    ] },
    { cells: [{ text: 'P1' }, { text: '0' }, { text: '3' }] },
  ],
})
assert(structured)
assert.strictEqual(structured.row_count, 3)
assert.strictEqual(structured.column_count, 3)
assert.strictEqual(structured.requires_review, false)
const prepared = table.prepareTableForRender(structured, {})
assert.strictEqual(prepared._cells.length, 7)
assert(prepared._cells[0]._cellStyle.includes('span 2'))

const legacy = table.normalizeTableSegment({
  type: 'table_markdown',
  markdown: '| 名称 | 数值 |\n| --- | --- |\n| A | 1 |',
})
assert(legacy)
assert.strictEqual(legacy.schema_version, 'table.v2')
assert.strictEqual(legacy.has_header, true)
assert.strictEqual(legacy.rows[1].cells[1].text, '1')

const invalid = table.normalizeTableSegment({
  type: 'table',
  rows: [{ cells: [{ text: 'A', row_span: 4 }] }],
})
assert(invalid.requires_review)
assert(invalid.signals.length > 0)

const invalidVerified = table.normalizeTableSegment({
  type: 'table',
  manual_verified: true,
  requires_review: false,
  rows: [{ cells: [{ text: 'A', row_span: 4 }] }],
})
assert(invalidVerified.requires_review)

const verified = table.normalizeTableSegment({
  type: 'table',
  confidence: 0.2,
  requires_review: true,
  manual_verified: true,
  rows: [{ cells: [{ text: '已核验' }] }],
})
assert(verified)
assert.strictEqual(verified.requires_review, false)

const tableOnlyModel = stemRender.buildRenderModel({
  id: 9001,
  content: {
    render_mode: 'segments',
    segments: [{
      type: 'table',
      rows: [{ cells: [{ text: '项目', is_header: true }, { text: '数值', is_header: true }] }],
    }],
  },
}, null, { enableMathImage: false, SAFE_MODE: false })
assert.strictEqual(tableOnlyModel.mode, stemRender.RENDER_MODE.SEGMENTS)
assert.strictEqual(tableOnlyModel.segments[0].type, 'table')
assert.strictEqual(tableOnlyModel.segments.length, 1)

console.log('table-structure tests passed')


var { isImageLikeSegmentType } = require('./segment-types')
var MAX_ROWS = 500
var MAX_COLUMNS = 100
function _record(value) {
return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}
function _number(value, fallback) {
var parsed = Number(value)
return isFinite(parsed) ? parsed : fallback
}
function _span(value) {
return Math.max(1, Math.min(MAX_COLUMNS, Math.floor(_number(value, 1))))
}
function _confidence(value, fallback) {
return Math.max(0, Math.min(1, _number(value, fallback == null ? 1 : fallback)))
}
function _alignment(value) {
var text = String(value || '').toLowerCase()
if (text.indexOf('center') >= 0) return 'center'
if (text.indexOf('right') >= 0) return 'right'
return 'left'
}
function contentToText(content) {
if (!Array.isArray(content)) return ''
return content.map(function (block) {
if (!block || typeof block !== 'object') return ''
if (String(block.type || '').toLowerCase() === 'newline') return '\n'
return String(block.text || block.alt || '')
}).join('').trim()
}
function _cell(value) {
var data = _record(value)
if (!data) {
var raw = String(value == null ? '' : value)
return { text: raw, content: [{ type: 'text', text: raw }], row_span: 1, col_span: 1, is_header: false, alignment: 'left', confidence: 1 }
}
var text = String(data.text == null ? contentToText(data.content) : data.text)
var content = Array.isArray(data.content)
? data.content.filter(function (block) { return block && typeof block === 'object' }).map(function (block) { return Object.assign({}, block) })
: [{ type: 'text', text: text }]
if (content.length === 0) content = [{ type: 'text', text: text }]
return {
text: text || contentToText(content),
content: content,
row_span: _span(data.row_span || data.rowspan),
col_span: _span(data.col_span || data.colspan),
is_header: !!data.is_header,
alignment: _alignment(data.alignment || data.align),
confidence: _confidence(data.confidence, 1),
}
}
function _splitMarkdownRow(line) {
var value = String(line || '').trim()
if (value.charAt(0) === '|') value = value.slice(1)
if (value.charAt(value.length - 1) === '|' && value.slice(-2) !== '\\|') value = value.slice(0, -1)
var cells = []
var current = ''
var escaped = false
for (var i = 0; i < value.length; i++) {
var ch = value.charAt(i)
if (escaped) {
current += ch
escaped = false
} else if (ch === '\\') {
escaped = true
} else if (ch === '|') {
cells.push(current.replace(/<br\s*\/?\s*>/gi, '\n').trim())
current = ''
} else {
current += ch
}
}
cells.push(current.replace(/<br\s*\/?\s*>/gi, '\n').trim())
return cells
}
function _legacyRows(markdown) {
var lines = String(markdown || '').split(/\r?\n/).map(function (line) { return line.trim() }).filter(Boolean)
if (lines.length < 2) return []
var separator = -1
for (var i = 0; i < lines.length; i++) {
if (/^\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$/.test(lines[i])) { separator = i; break }
}
var headerIndex = separator > 0 ? separator - 1 : -1
return lines.filter(function (_, index) { return index !== separator }).map(function (line, index) {
return {
cells: _splitMarkdownRow(line).map(function (text) {
var cell = _cell(text)
cell.is_header = headerIndex >= 0 && index === headerIndex
return cell
})
}
})
}
function buildLayout(rows) {
var occupied = {}
var anchors = []
var issues = []
var columnCount = 0
;(rows || []).slice(0, MAX_ROWS).forEach(function (row, rowIndex) {
var column = 0
;(row.cells || []).forEach(function (cell, cellIndex) {
while (occupied[rowIndex + ':' + column] && column < MAX_COLUMNS) column++
if (column >= MAX_COLUMNS) {
issues.push('第 ' + (rowIndex + 1) + ' 行第 ' + (cellIndex + 1) + ' 个单元格超出最大列数')
return
}
var rowSpan = Math.min(cell.row_span, Math.max(1, rows.length - rowIndex))
var colSpan = Math.min(cell.col_span, Math.max(1, MAX_COLUMNS - column))
if (rowSpan !== cell.row_span) issues.push('存在越界行合并')
if (colSpan !== cell.col_span) issues.push('存在越界列合并')
for (var rr = rowIndex; rr < rowIndex + rowSpan; rr++) {
for (var cc = column; cc < column + colSpan; cc++) {
var key = rr + ':' + cc
if (occupied[key]) issues.push('单元格重叠')
occupied[key] = true
}
}
anchors.push({ row: rowIndex, column: column, cell: Object.assign({}, cell, { row_span: rowSpan, col_span: colSpan }) })
column += colSpan
columnCount = Math.max(columnCount, column)
})
})
if (!rows || rows.length === 0) issues.push('表格没有数据行')
if (columnCount < 1) issues.push('表格没有有效列')
return { anchors: anchors, rowCount: (rows || []).length, columnCount: columnCount, issues: issues.filter(function (item, index, list) { return list.indexOf(item) === index }) }
}
function normalizeTableSegment(segment) {
var data = _record(segment)
if (!data) return null
var type = String(data.type || '').toLowerCase()
var rows = []
if (type === 'table' && Array.isArray(data.rows)) {
rows = data.rows.slice(0, MAX_ROWS).map(function (rawRow) {
var row = _record(rawRow)
var rawCells = row && Array.isArray(row.cells) ? row.cells : (Array.isArray(rawRow) ? rawRow : [])
return { cells: rawCells.map(_cell) }
})
} else if (type === 'table_markdown' || typeof data.markdown === 'string') {
rows = _legacyRows(data.markdown || data.text || data.content || '')
} else {
return null
}
if (rows.length === 0) return null
var layout = buildLayout(rows)
var confidence = _confidence(data.confidence, type === 'table' ? 1 : 0.7)
var pages = Array.isArray(data.source_pages) ? data.source_pages.map(function (page) { return Math.floor(_number(page, 0)) }).filter(function (page) { return page > 0 }) : []
var sourcePage = Math.floor(_number(data.source_page, pages[0] || 0))
if (sourcePage > 0 && pages.indexOf(sourcePage) < 0) pages.unshift(sourcePage)
var manuallyVerified = !!data.manual_verified
return Object.assign({}, data, {
type: 'table',
schema_version: 'table.v2',
caption: String(data.caption || ''),
rows: rows,
row_count: rows.length,
column_count: layout.columnCount,
has_header: rows.some(function (row) { return row.cells.some(function (cell) { return cell.is_header }) }),
source_pages: pages.filter(function (page, index, list) { return list.indexOf(page) === index }).sort(function (a, b) { return a - b }),
confidence: confidence,
requires_review: layout.issues.length > 0 || (!manuallyVerified && (!!data.requires_review || confidence < 0.65)),
signals: (Array.isArray(data.signals) ? data.signals.map(String) : []).concat(layout.issues).filter(function (item, index, list) { return list.indexOf(item) === index }),
_layout: layout,
})
}
function _prepareBlock(block, helpers) {
var type = String(block.type || 'text').toLowerCase()
if (type === 'newline') return { type: 'newline' }
if (isImageLikeSegmentType(type)) {
return {
type: 'image',
url: block.url && helpers.resolveAssetUrl ? helpers.resolveAssetUrl(block.url) : String(block.url || ''),
alt: String(block.alt || ''),
_error: false,
}
}
var text = String(block.text || block.alt || '')
var needsRich = helpers.needsRichRender ? helpers.needsRichRender(text) : false
return {
type: 'text',
text: text,
needsRich: needsRich,
html: needsRich && helpers.textToHtml ? helpers.textToHtml(text) : '',
}
}
function prepareTableForRender(segment, helpers) {
var table = normalizeTableSegment(segment)
if (!table) return null
helpers = helpers || {}
var layout = table._layout || buildLayout(table.rows)
var cells = layout.anchors.map(function (anchor, index) {
var cell = anchor.cell
var blocks = (Array.isArray(cell.content) ? cell.content : [{ type: 'text', text: cell.text }]).map(function (block) {
return _prepareBlock(block, helpers)
})
return {
_key: anchor.row + '-' + anchor.column + '-' + index,
_text: cell.text || contentToText(cell.content),
_blocks: blocks,
_isHeader: !!cell.is_header,
_className: 'seg-table-cell' + (cell.is_header ? ' seg-table-cell-header' : ''),
_cellStyle: 'grid-row:' + (anchor.row + 1) + ' / span ' + cell.row_span + ';grid-column:' + (anchor.column + 1) + ' / span ' + cell.col_span + ';text-align:' + cell.alignment + ';',
}
})
var pageLabel = ''
if (table.source_pages.length === 1) pageLabel = '第' + table.source_pages[0] + '页'
else if (table.source_pages.length > 1) pageLabel = '第' + table.source_pages[0] + '–' + table.source_pages[table.source_pages.length - 1] + '页'
var sourceImage = table.source_image_url || table.fallback_image_url || ''
if (sourceImage && helpers.resolveAssetUrl) sourceImage = helpers.resolveAssetUrl(sourceImage)
var renderTable = Object.assign({}, table)
delete renderTable._layout
return Object.assign(renderTable, {
_cells: cells,
_columnCount: Math.max(1, layout.columnCount),
_minWidth: Math.max(700, Math.max(1, layout.columnCount) * 180),
_gridStyle: 'grid-template-columns:repeat(' + Math.max(1, layout.columnCount) + ',minmax(160rpx,1fr));min-width:' + Math.max(700, Math.max(1, layout.columnCount) * 180) + 'rpx;',
_confidenceText: Math.round(table.confidence * 100) + '%',
_pageLabel: pageLabel,
_sourceImageUrl: sourceImage,
_sourceImageError: false,
_invalid: layout.issues.length > 0,
_issueText: layout.issues.join('；'),
})
}
function tableToText(segment) {
var table = normalizeTableSegment(segment)
if (!table) return ''
return table.rows.map(function (row) {
return row.cells.map(function (cell) { return cell.text || contentToText(cell.content) }).join('\t')
}).join('\n')
}
function hasTableSegments(segments) {
return Array.isArray(segments) && segments.some(function (segment) {
var type = segment && typeof segment === 'object' ? String(segment.type || '').toLowerCase() : ''
return type === 'table' || type === 'table_markdown'
})
}
module.exports = {
normalizeTableSegment: normalizeTableSegment,
prepareTableForRender: prepareTableForRender,
buildLayout: buildLayout,
contentToText: contentToText,
tableToText: tableToText,
hasTableSegments: hasTableSegments,
}

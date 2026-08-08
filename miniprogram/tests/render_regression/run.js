/**
 * Historical render regression test runner.
 * Run: cd miniprogram && node tests/render_regression/run.js
 *
 * Rule: any future stem duplication bug MUST add a fixture here before fixing.
 */
var fs = require('fs')
var path = require('path')
var { RENDER_MODE, buildRenderModel, resetRenderGuard, setRenderGuardPage, buildRichTextNodes } = require('../../subpackages/study/utils/stem-render')

var mockConfig = { enableMathImage: false, DEV: true }

function _extractRichTextText(nodes) {
  if (!Array.isArray(nodes)) return ''
  var r = ''
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i].type === 'text') r += nodes[i].text
    if (nodes[i].children) r += _extractRichTextText(nodes[i].children)
  }
  return r
}

function _getVisibleText(result) {
  if (result.mode === 'RICH_TEXT') return _extractRichTextText(result.richTextNodes)
  if (result.mode === 'LATEX') return result.html.replace(/<[^>]+>/g, '')
  if (result.mode === 'CODE') return result.rawText
  if (result.mode === 'MIXED' && Array.isArray(result.blocks)) {
    return result.blocks.map(function (b) {
      if (b.type === 'RICH_TEXT') return _extractRichTextText(b.richTextNodes)
      if (b.type === 'LATEX') return b.html ? b.html.replace(/<[^>]+>/g, '') : ''
      if (b.type === 'CODE') return b.rawText
      return ''
    }).join(' ')
  }
  return ''
}
var passed = 0
var failed = 0
var fixtureDir = __dirname

function assert(condition, msg) {
  if (condition) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
}

function assertEq(actual, expected, msg) {
  if (actual === expected) { passed++; return }
  failed++
  console.error('  FAIL:', msg)
  console.error('    expected:', JSON.stringify(expected))
  console.error('    actual:', JSON.stringify(actual))
}

var files = fs.readdirSync(fixtureDir).filter(function (f) { return f.endsWith('.json') }).sort()

files.forEach(function (file) {
  var fixture = JSON.parse(fs.readFileSync(path.join(fixtureDir, file), 'utf8'))
  console.log('\n' + file + ' — ' + fixture._bug)

  setRenderGuardPage('render_regression:' + file)
  resetRenderGuard()

  var q = fixture.question
  var result = buildRenderModel(q, q.options, mockConfig)

  assertEq(result.mode, fixture.expected.mode, 'mode matches: ' + fixture.expected.mode)

  if (fixture.expected.hasHtml) {
    assert(result.html.length > 0, 'html is populated')
  } else {
    assertEq(result.html, '', 'html is empty')
  }

  if (fixture.expected.hasRawText) {
    assert(result.rawText.length > 0, 'rawText is populated')
  } else {
    assertEq(result.rawText, '', 'rawText is empty')
  }

  if (fixture.expected.hasRichTextNodes) {
    assert(result.richTextNodes.length > 0, 'richTextNodes is populated')
  } else {
    assertEq(result.richTextNodes.length, 0, 'richTextNodes is empty')
  }

  // Verify single render root (MIXED counts as one when blocks is non-empty)
  var activeCount = [
    result.mode === RENDER_MODE.RICH_TEXT && result.richTextNodes.length > 0,
    result.mode === RENDER_MODE.LATEX && result.html.length > 0,
    result.mode === RENDER_MODE.SEGMENTS && result.segments.length > 0,
    result.mode === RENDER_MODE.CODE && result.rawText.length > 0,
    result.mode === RENDER_MODE.MIXED && result.blocks && result.blocks.length > 0
  ].filter(Boolean).length
  assertEq(activeCount, 1, 'exactly one render root active')

  if (fixture.expected.visibleTextContains) {
    var visible = _getVisibleText(result)
    assert(visible.indexOf(fixture.expected.visibleTextContains) >= 0,
      'visibleText contains: ' + fixture.expected.visibleTextContains)
  }

  // MIXED mode: blocks must be non-empty and each block must have valid type
  if (result.mode === 'MIXED') {
    assert(Array.isArray(result.blocks) && result.blocks.length > 0, 'MIXED has non-empty blocks')
    for (var bi = 0; bi < result.blocks.length; bi++) {
      var block = result.blocks[bi]
      assert(block.type === 'RICH_TEXT' || block.type === 'LATEX' || block.type === 'CODE',
        'block #' + bi + ' has valid type: ' + block.type)
      if (block.type === 'RICH_TEXT') assert(block.richTextNodes && block.richTextNodes.length > 0, 'RICH_TEXT block has nodes')
      if (block.type === 'LATEX') assert(block.html && block.html.length > 0, 'LATEX block has html')
      if (block.type === 'CODE') assert(block.rawText && block.rawText.length > 0, 'CODE block has rawText')
    }
  }
})

console.log('\n' + '='.repeat(50))
console.log('Regression fixtures: ' + files.length)
console.log('Total: ' + (passed + failed) + '  Passed: ' + passed + '  Failed: ' + failed)
if (failed > 0) {
  console.error('\nSOME REGRESSION TESTS FAILED')
  process.exit(1)
} else {
  console.log('\nAll regression tests passed.')
}

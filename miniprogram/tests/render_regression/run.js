/**
 * Historical render regression test runner.
 * Run: cd miniprogram && node tests/render_regression/run.js
 *
 * Rule: any future stem duplication bug MUST add a fixture here before fixing.
 */
var fs = require('fs')
var path = require('path')
var { RENDER_MODE, buildRenderModel, resetRenderGuard, setRenderGuardPage } = require('../../utils/stem-render')

var mockConfig = { enableMathImage: false, DEV: true }
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

  if (fixture.expected.hasRichTextNodes) {
    assert(result.richTextNodes.length > 0, 'richTextNodes is populated')
  } else {
    assertEq(result.richTextNodes.length, 0, 'richTextNodes is empty')
  }

  // Verify single render root
  var activeCount = [
    result.mode === RENDER_MODE.RICH_TEXT && result.richTextNodes.length > 0,
    result.mode === RENDER_MODE.LATEX && result.html.length > 0,
    result.mode === RENDER_MODE.SEGMENTS && result.segments.length > 0
  ].filter(Boolean).length
  assertEq(activeCount, 1, 'exactly one render root active')
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

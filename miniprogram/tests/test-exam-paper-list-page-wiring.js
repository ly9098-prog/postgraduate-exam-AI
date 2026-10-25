const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')

const pageSource = fs.readFileSync(
  path.resolve(__dirname, '../subpackages/exam/paper-list/index.js'),
  'utf8'
)

function method(name) {
  const start = pageSource.indexOf(`  _${name}() {`)
  assert.ok(start >= 0, `missing _${name}`)
  const end = pageSource.indexOf('\n  },', start)
  return pageSource.slice(start, end)
}

test('loadPapers delegates to the paper list load controller', () => {
  const source = method('paperListLoadController')
  assert.ok(source.includes('createPaperListLoadController'))
  assert.ok(source.includes('buildPapers(rows, this.data.suggestedPaperId)'))
  assert.ok(source.includes("api.get('/exams/papers')"))
  assert.ok(source.includes('api.getErrorMessage(error)'))
  assert.ok(source.includes('wx.showToast(options)'))
  assert.ok(source.includes('this._commitPapers(papers, commitOptions)'))
  assert.ok(source.includes('this._loadedOnce = true'))
  assert.ok(source.includes('this._loadGeneration = (this._loadGeneration || 0) + 1'))
})

test('page wiring exposes the exact controller port set', () => {
  const source = method('paperListLoadController')
  const expectedPorts = [
    'nextGeneration',
    'getGeneration',
    'isPageAlive',
    'wasLoadedOnce',
    'markLoadedOnce',
    'getErrorText',
    'setData',
    'getPapers',
    'getErrorMessage',
    'showToast',
    'buildPapers',
    'commitPapers',
  ]
  for (const port of expectedPorts) {
    assert.ok(source.includes(`${port}:`), `missing port wiring: ${port}`)
  }
  // No unexpected extra ports
  const portMatches = source.match(/^\s{8}([A-Za-z]\w*):/gm) || []
  const actualPorts = portMatches.map(match => match.trim().replace(':', ''))
  assert.deepEqual([...actualPorts].sort(), [...expectedPorts].sort())
})

test('controller instance is cached under a matching private name', () => {
  const source = method('paperListLoadController')
  assert.ok(source.includes('if (!this._paperListLoad)'))
  assert.ok(source.includes('return this._paperListLoad'))
  assert.ok(!source.includes('_paperLoadController'), 'stale cached-property name must not remain')
})

test('loadPapers method is a thin delegate', () => {
  const start = pageSource.indexOf('  async loadPapers(options = {}) {')
  assert.ok(start >= 0)
  const end = pageSource.indexOf('\n  },', start)
  const source = pageSource.slice(start, end)
  assert.ok(source.includes('return this._paperListLoadController().load(options)'))
  assert.ok(source.split('\n').length <= 4)
})

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')

const pageSource = fs.readFileSync(
  path.resolve(__dirname, '../subpackages/exam/result/index.js'),
  'utf8'
)

function method(name) {
  const start = pageSource.indexOf(`  _${name}() {`)
  assert.ok(start >= 0, `missing _${name}`)
  const end = pageSource.indexOf('\n  },', start)
  return pageSource.slice(start, end)
}

test('loadResult delegates to the exam result load controller', () => {
  const start = pageSource.indexOf('  async loadResult(options = {}) {')
  assert.ok(start >= 0, 'missing loadResult')
  const end = pageSource.indexOf('\n  },', start)
  const source = pageSource.slice(start, end)
  assert.ok(source.includes('return this._examResultLoadController().load(options)'))
  assert.ok(source.split('\n').length <= 4)
})

test('exam result load wiring exposes the exact controller port set', () => {
  const source = method('examResultLoadController')
  const expectedPorts = [
    'getInflight',
    'setInflight',
    'nextSequence',
    'getSequence',
    'isPageAlive',
    'setData',
    'fetchResult',
    'getErrorMessage',
    'percentNumber',
    'clamp',
    'compactScore',
    'compactDuration',
    'encouragement',
    'encouragementTail',
    'buildKnowledgeMetrics',
    'buildScoreRing',
    'buildRadar',
    'buildTopItems',
    'collectWrongIds',
    'firstWrongIdByQuestion',
    'setWrongIds',
    'getWrongIdsLength',
    'resetDiagnosisIndex',
    'setDiagnosisId',
    'setFirstQuestionId',
  ]
  for (const port of expectedPorts) {
    // Ports may be wired as `port:` (arrow/long form) or `port,` (shorthand).
    assert.ok(
      source.includes(`${port}:`) || source.includes(`${port},`),
      `missing port wiring: ${port}`
    )
  }
  // Match both `port:` and `port,` shorthand forms at 8-space indent.
  const portMatches = source.match(/^\s{8}([A-Za-z]\w*)(?:[:,])/gm) || []
  const actualPorts = portMatches.map(match => match.trim().replace(/[:,]/, ''))
  assert.deepEqual([...actualPorts].sort(), [...expectedPorts].sort())
})

test('exam result load ports are wired to exact page helpers', () => {
  const source = method('examResultLoadController')
  assert.ok(source.includes("api.get(`/exams/attempts/${this.data.attemptId}/result`)"))
  assert.ok(source.includes('api.getErrorMessage(error)'))
  assert.ok(source.includes('this._wrongIds = ids'))
  assert.ok(source.includes('this._wrongIds.length'))
  assert.ok(source.includes('this._diagnosisIdByWrongId = Object.create(null)'))
  assert.ok(source.includes('this._diagnosisIdByWrongId[wrongId] = diagnosisId'))
  assert.ok(source.includes('this._firstQuestionId = id'))
})

test('exam result load cached field name is stable', () => {
  const source = method('examResultLoadController')
  assert.ok(source.includes('if (!this._examResultLoad)'))
  assert.ok(source.includes('this._examResultLoad = createExamResultLoadController'))
  assert.ok(source.includes('return this._examResultLoad'))
})

test('run408Teacher delegates to the exam 408 teacher controller', () => {
  const start = pageSource.indexOf('  async run408Teacher(action, questionId) {')
  assert.ok(start >= 0, 'missing run408Teacher')
  const end = pageSource.indexOf('\n  },', start)
  const source = pageSource.slice(start, end)
  assert.ok(source.includes('return this._exam408TeacherController().run(action, questionId)'))
  assert.ok(source.split('\n').length <= 4)
})

test('exam 408 teacher wiring exposes the exact controller port set', () => {
  const source = method('exam408TeacherController')
  const expectedPorts = [
    'getAttemptId',
    'getTeacherLoading',
    'isPageAlive',
    'setData',
    'getCacheEntry',
    'setCacheEntry',
    'getFeedbackEntry',
    'setActiveCacheKey',
    'getInflight',
    'setInflight',
    'deleteInflight',
    'nextRequestSequence',
    'getRequestSequence',
    'postTeacher',
    'normalizeResult',
    'errorMessage',
  ]
  for (const port of expectedPorts) {
    assert.ok(source.includes(`${port}:`), `missing port wiring: ${port}`)
  }
  const portMatches = source.match(/^\s{8}([A-Za-z]\w*):/gm) || []
  const actualPorts = portMatches.map(match => match.trim().replace(':', ''))
  assert.deepEqual([...actualPorts].sort(), [...expectedPorts].sort())
})

test('exam 408 teacher ports are wired to exact page helpers', () => {
  const source = method('exam408TeacherController')
  assert.ok(source.includes("api.post('/ai/408-teacher', payload, { timeout: 55000 })"))
  assert.ok(source.includes('aiTeacher408.normalizeResult(raw)'))
  assert.ok(source.includes('aiTeacher408.errorMessage(error, api)'))
  assert.ok(source.includes('this._teacherCache[key]'))
  assert.ok(source.includes('this._teacherFeedbackCache[key]'))
  assert.ok(source.includes('this._teacherInflight[key]'))
  assert.ok(source.includes('delete this._teacherInflight[key]'))
  assert.ok(source.includes('this._activeTeacherCacheKey = key'))
  assert.ok(source.includes('++this._teacherRequestSeq'))
})

test('exam 408 teacher cached field name is stable', () => {
  const source = method('exam408TeacherController')
  assert.ok(source.includes('if (!this._exam408Teacher)'))
  assert.ok(source.includes('this._exam408Teacher = createExam408TeacherController'))
  assert.ok(source.includes('return this._exam408Teacher'))
})

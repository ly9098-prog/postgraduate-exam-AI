const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')

const {
  PAGES, FUNCTION_BUDGET, violations,
} = require('../scripts/architecture/page-budgets')

const root = path.resolve(__dirname, '../..')
const relative = Object.keys(PAGES)[0]

test('all governed home, learning, exam, review, statistics and pomodoro pages stay within budgets', () => {
  assert.equal(Object.keys(PAGES).length, 12)
  assert.deepEqual(violations(), [])
})

test('line ceiling can shrink but must not silently grow', () => {
  const source = fs.readFileSync(path.join(root, 'miniprogram', relative), 'utf8')
  assert.ok(source.trimEnd().split('\n').length <= PAGES[relative])
})

test('function budget rejects nested and method regressions', () => {
  assert.equal(FUNCTION_BUDGET, 50)
  const body = Array(50).fill('void 0').join('\n')
  for (const source of [
    `function long() {\n${body}\n}`,
    `const owner = { async long() {\n${body}\n} }`,
  ]) assert.ok(violations.forFixture(source).length > 0, source)
})

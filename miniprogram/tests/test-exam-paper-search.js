const assert = require('node:assert/strict')
const { test } = require('node:test')
const { normalizeSearchValue, fuzzyIncludes, matchesPaper, paperRenderSignature } = require('../subpackages/exam/utils/paper-search')

test('normalizeSearchValue: lowercases and strips noise', () => {
  assert.equal(normalizeSearchValue('Hello 408 World'), 'helloworld')
})

test('normalizeSearchValue: strips punctuation', () => {
  assert.equal(normalizeSearchValue('数据结构-操作系统'), '数据结构操作系统')
})

test('normalizeSearchValue: handles null', () => {
  assert.equal(normalizeSearchValue(null), '')
})

test('fuzzyIncludes: exact match', () => {
  assert.equal(fuzzyIncludes('abcdef', 'abc'), true)
})

test('fuzzyIncludes: subsequence match', () => {
  assert.equal(fuzzyIncludes('axbycz', 'abc'), true)
})

test('fuzzyIncludes: no match', () => {
  assert.equal(fuzzyIncludes('xyz', 'abc'), false)
})

test('fuzzyIncludes: empty term always matches', () => {
  assert.equal(fuzzyIncludes('anything', ''), true)
})

test('matchesPaper: returns true for empty query', () => {
  assert.equal(matchesPaper({ title: 'Test' }, ''), true)
})

test('matchesPaper: matches by title', () => {
  assert.equal(matchesPaper({ title: '数据结构真题' }, '数据'), true)
})

test('matchesPaper: no match for unrelated query', () => {
  assert.equal(matchesPaper({ title: '数据结构' }, '操作系统'), false)
})

test('matchesPaper: matches by question count', () => {
  assert.equal(matchesPaper({ title: 'Test', question_count: 40 }, '40题'), true)
})

test('paperRenderSignature: produces stable signature', () => {
  const papers = [{ id: 1, title: 'A' }, { id: 2, title: 'B' }]
  const sig1 = paperRenderSignature(papers)
  const sig2 = paperRenderSignature(papers)
  assert.equal(sig1, sig2)
})

test('paperRenderSignature: different papers produce different signatures', () => {
  const sig1 = paperRenderSignature([{ id: 1, title: 'A' }])
  const sig2 = paperRenderSignature([{ id: 2, title: 'B' }])
  assert.notEqual(sig1, sig2)
})

test('paperRenderSignature: handles empty array', () => {
  assert.equal(paperRenderSignature([]), '')
})

test('paperRenderSignature: handles non-array', () => {
  assert.equal(paperRenderSignature(null), '')
})

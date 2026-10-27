const assert = require('node:assert/strict')
const { test } = require('node:test')
const { runner, question, plain } = require('./quiz-runner-component-support')

for (const pkg of ['study', 'exam']) {
  for (const match of [true, false]) {
    test(`${pkg}: answer identity ${match} chooses references without copying`, () => {
      const r = runner(pkg)
      const q = question(4)
      q.question_type = 'multi_blank_multiple_choice'
      q._blankOptionGroups = [{ blankId: 'q' }]
      q._optionList = [{ key: 'q' }]
      const state = { questionId: match ? '4' : 5, blankOptionGroups: [{ blankId: 'state' }],
        optionList: [{ key: 'state' }] }
      r.observe(q, state)
      assert.equal(r.target.data._blankOptionGroups, match ? state.blankOptionGroups : q._blankOptionGroups)
      assert.equal(r.target.data._optionList, match ? state.optionList : q._optionList)
      assert.equal(r.target.data._hasBlankOptionGroups, true)
      assert.equal(r.target.data._isMultiBlankMultiple, true)
    })
  }

  for (const text of ['ready', '', undefined]) {
    test(`${pkg}: first blank option text ${String(text)} controls enrichment`, () => {
      const groups = [{ blankId: 1, options: [{ _text: text }] }]
      const enriched = [{ blankId: 2, options: [{ _text: 'enriched' }] }]
      const calls = []
      const adapter = {
        getBlankOptionGroups(q) { calls.push(['groups', q]); return groups },
        enrichBlankOptionGroups(value, answer) { calls.push(['enrich', value, answer]); return enriched },
        buildOptionListFromFlags() {
          calls.push(['build'])
          throw Error('blank groups suppress ordinary fallback')
        },
      }
      const r = runner(pkg, { adapter: () => adapter })
      const q = question()
      q._blankAnswer = 'A|B'
      q.user_answer = 'unused'
      r.observe(q, null)
      assert.equal(calls[0][0], 'groups')
      assert.equal(calls[0][1], q)
      assert.equal(calls.length, text ? 1 : 2)
      assert.equal(r.target.data._blankOptionGroups, text ? groups : enriched)
      if (!text) {
        assert.equal(calls[1][1], groups)
        assert.equal(calls[1][2], 'A|B')
      }
      assert.deepEqual(plain(r.target.data._optionList), [])
    })
  }

  for (const stage of ['groups', 'enrich', 'options', 'build']) {
    test(`${pkg}: optional ${stage} failure preserves answer projection`, () => {
      const error = new Error('optional failure')
      const r = runner(pkg, { adapter: () => ({
        getBlankOptionGroups() { if (stage === 'groups') throw error; return [] },
        enrichBlankOptionGroups() { throw error },
        getQuestionOptions() { if (stage === 'options') throw error; return { A: 'value' } },
        buildOptionListFromFlags() { if (stage === 'build') throw error; return [{ key: 'A' }] },
      }) })
      const q = question()
      if (stage === 'enrich') q._blankOptionGroups = [{ options: [] }]
      r.observe(q, null)
      assert.equal(r.writes.length, 1)
      assert.equal(r.target.data._displayQuestion, q)
      assert.equal(r.target.data._optionList.length, stage === 'groups' ? 1 : 0)
      if (stage === 'enrich') assert.equal(r.target.data._blankOptionGroups, q._blankOptionGroups)
    })
  }

  for (const source of ['cached', 'adapter', 'question']) {
    test(`${pkg}: ordinary option source ${source} keeps keys and flags`, () => {
      const values = { B: 'beta', A: 'alpha' }
      const keys = ['A', 'B']
      const flags = { B: true }
      const result = [{ key: 'B' }]
      let received
      let sourceCalls = 0
      const adapter = {
        buildOptionListFromFlags(...args) { received = args; return result },
      }
      if (source !== 'question') adapter.getQuestionOptions = () => {
        sourceCalls++
        return source === 'cached' ? { C: 'must not read' } : values
      }
      const r = runner(pkg, { adapter: () => adapter })
      const q = question()
      q.options = values
      q._opts = source === 'cached' ? values : {}
      q._optionKeys = keys
      q._selectedFlags = flags
      r.observe(q, null)
      assert.equal(received[0], values)
      assert.equal(received[1], keys)
      assert.equal(received[2], flags)
      assert.equal(r.target.data._optionList, result)
      assert.equal(sourceCalls, source === 'adapter' ? 1 : 0)
    })
  }

  test(`${pkg}: nonmatching state never supplies cached answers`, () => {
    const r = runner(pkg)
    const q = question(2)
    r.observe(q, { questionId: 1, optionList: [{ key: 'A' }], blankOptionGroups: [{}] })
    assert.deepEqual(plain(r.target.data._optionList), [])
    assert.deepEqual(plain(r.target.data._blankOptionGroups), [])
  })
}

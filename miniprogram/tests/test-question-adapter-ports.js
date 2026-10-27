const assert = require('node:assert/strict')
const vm = require('node:vm')
const { test } = require('node:test')
const { loadAdapter, plain, signatures } = require('./question-adapter-support')

for (const pkg of ['study', 'exam']) {
  test(`${pkg}: public names, order, arity and leaf binding remain stable`, () => {
    const reads = []
    const unread = new Proxy({}, { get(target, key) { reads.push(key); throw Error('early read') } })
    const loaded = loadAdapter(pkg, { stem: unread, answer: unread })
    assert.deepEqual(Object.keys(loaded.adapter), Object.keys(signatures))
    for (const [name, arity] of Object.entries(signatures)) {
      assert.equal(loaded.adapter[name].name, name)
      assert.equal(loaded.adapter[name].length, arity)
    }
    assert.deepEqual(loaded.imports.filter(name => name === './stem-render' || name === './answer'),
      ['./stem-render', './answer'])
    assert.deepEqual(reads, [])
  })

  test(`${pkg}: renderer method lookup stays live with original arguments and receiver`, () => {
    const result = [], opts = { A: 'one' }, keys = ['A'], flags = { A: true }
    const stem = { buildOptionList() { throw Error('stale method') } }
    const { adapter } = loadAdapter(pkg, { stem })
    stem.buildOptionList = function (...args) {
      assert.equal(this, stem)
      assert.equal(args[0], opts)
      assert.equal(args[1], keys)
      assert.equal(args[2], flags)
      return result
    }
    assert.equal(adapter.buildOptionListFromFlags(opts, keys, flags), result)
  })

  test(`${pkg}: answer normalizer lookup stays live on the captured answer object`, () => {
    const answer = { normalizeBlankAnswer() { throw Error('stale method') } }
    const { adapter } = loadAdapter(pkg, { answer })
    const source = {}, slots = ['slot']
    answer.normalizeBlankAnswer = function (value, slotIds) {
      assert.equal(this, answer)
      assert.equal(value, source)
      assert.equal(slotIds, slots)
      return { slot: ' b ' }
    }
    assert.deepEqual(plain(adapter.normalizeBlankAnswer(source, slots)), { slot: 'B' })
  })

  test(`${pkg}: public method replacement does not replace internal answer-count bindings`, () => {
    const { adapter } = loadAdapter(pkg)
    adapter.isQuestionAnswered = () => { throw Error('public override must not be used') }
    assert.equal(adapter.computeAnsweredCount([{ id: 1 }], { 1: 'A' }), 1)
    assert.deepEqual(plain(adapter.buildAnsweredFlags([{ id: 1 }], { 1: 'A' })), { 1: true })
  })

  test(`${pkg}: hasOwn is captured before later prototype changes`, () => {
    const loaded = loadAdapter(pkg)
    vm.runInContext("Object.prototype.hasOwnProperty = function () { throw Error('late lookup') }",
      loaded.context)
    assert.deepEqual(plain(loaded.adapter.normalizeBlankOptionList({ options: { A: 'one' } })),
      [{ key: 'A', text: 'one' }])
    assert.equal(loaded.adapter.getBlankOptionGroups({ blank_option_groups: [
      { marker: 'slot', choices: { A: 'one' } },
    ] })[0].id, 'slot')
  })

  test(`${pkg}: legacy blank correctness calls the exact single-choice port`, () => {
    const sentinel = {}
    const answer = { isAnswerCorrect(...args) {
      assert.equal(this, answer)
      assert.deepEqual(args, ['b', 'B', 'single_choice'])
      return sentinel
    } }
    const { adapter } = loadAdapter(pkg, { answer })
    const q = { question_type: 'multi_blank_choice', answer: 'B', options: { A: 'one', B: 'two' } }
    assert.equal(adapter.isAnswerCorrect(q, 'b'), sentinel)
  })

  test(`${pkg}: correctness aliases and type getters retain their read sequence`, () => {
    const reads = []
    const q = {
      get answer() { reads.push('answer'); return '' },
      get correct_answer() { reads.push('correct'); return 'C' },
      get standard_answer() { throw Error('late alias') },
      get question_type() { reads.push('type'); return 'single_choice' },
    }
    assert.equal(loadAdapter(pkg).adapter.isAnswerCorrect(q, 'c'), true)
    assert.deepEqual(reads, ['answer', 'correct', 'type', 'type', 'type', 'type', 'type'])
  })

  test(`${pkg}: content getter failure precedes option candidates and preserves identity`, () => {
    const error = new Error('content failure')
    const q = { get content() { throw error }, get options() { throw Error('late options') } }
    assert.throws(() => loadAdapter(pkg).adapter.getBlankOptionGroups(q), value => value === error)
  })

  test(`${pkg}: option property getters are copied once in original enumeration order`, () => {
    const reads = [], metadata = {}
    const option = {
      get key() { reads.push('key'); return ' A ' },
      get text() { reads.push('text'); return 'one' },
      get metadata() { reads.push('metadata'); return metadata },
    }
    const result = loadAdapter(pkg).adapter.normalizeBlankOptionList([option])
    assert.deepEqual(reads, ['key', 'text', 'metadata'])
    assert.equal(result[0].key, 'A')
    assert.equal(result[0].metadata, metadata)
  })

  test(`${pkg}: nullable type predicates retain original non-boolean results`, () => {
    const { adapter } = loadAdapter(pkg)
    assert.equal(adapter.isMultiBlankChoice(null), null)
    assert.equal(adapter.isMultiBlankMultipleChoice(undefined), undefined)
    assert.equal(adapter.isMultiBlankChoice(0), 0)
  })
}

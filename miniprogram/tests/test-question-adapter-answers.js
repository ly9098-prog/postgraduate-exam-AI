const assert = require('node:assert/strict')
const { test } = require('node:test')
const { loadAdapter, plain } = require('./question-adapter-support')

function blankQuestion() {
  return { id: 7, question_type: 'multi_blank_multiple_choice', answer: '1:A,B;2:C',
    blank_option_groups: [
      { id: '1', options: { A: 'A. alpha', B: 'B. beta', C: 'C. gamma' } },
      { id: '2', options: { A: 'A. alpha', C: 'C. gamma' } },
    ] }
}

for (const pkg of ['study', 'exam']) {
  test(`${pkg}: canonical blank normalization copies and trims values`, () => {
    const source = { ' 1 ': ' a,b ', ' ': 'discard', two: null }
    const { adapter } = loadAdapter(pkg)
    assert.deepEqual(plain(adapter.normalizeBlankAnswer(source)), { 1: 'A,B', two: '' })
    assert.equal(source[' 1 '], ' a,b ')
  })

  test(`${pkg}: blank selection and readonly flags retain per-slot answers`, () => {
    const { adapter } = loadAdapter(pkg)
    const q = blankQuestion()
    const groups = adapter.getBlankOptionGroups(q)
    const editable = adapter.enrichBlankOptionGroups(groups, '1:B;2:A')
    assert.deepEqual(Array.from(editable[0].options, opt => opt._selected), [false, true, false])
    assert.deepEqual(Array.from(editable[1].options, opt => opt._selected), [true, false])
    const readonly = adapter.enrichBlankOptionGroupsReadonly(groups, q.answer, '1:B;2:A')
    const flags = readonly.map(group => group.options.map(opt =>
      [opt.key, opt._isCorrect, opt._isUserAnswer, opt._isBoth]))
    assert.deepEqual(plain(flags), [
      [['A', true, false, false], ['B', true, true, true], ['C', false, false, false]],
      [['A', false, true, false], ['C', true, false, false]],
    ])
    assert.equal(Object.hasOwn(readonly[0].options[0], '_selected'), false)
    assert.equal(groups[0].options.A, 'A. alpha')
  })

  test(`${pkg}: answer completeness, counting and copied question flags agree`, () => {
    const { adapter } = loadAdapter(pkg)
    const q = blankQuestion()
    const ordinary = { id: 8, question_type: 'single_choice' }
    const questions = [q, ordinary]
    const incomplete = { 7: '1:A', 8: 'B' }, complete = { 7: '1:A;2:C', 8: 'B' }
    assert.equal(adapter.isQuestionAnswered(q, incomplete), false)
    const flags = adapter.buildAnsweredFlags(questions, complete)
    assert.deepEqual(plain(flags), { 7: true, 8: true })
    assert.equal(adapter.countAnswered(flags), 2)
    assert.equal(adapter.computeAnsweredCount(questions, incomplete), 1)
    const copies = adapter.applyAnsweredFlags(questions, flags)
    assert.notEqual(copies[0], q)
    assert.equal(copies[0].blank_option_groups, q.blank_option_groups)
    assert.equal(copies[0]._answered, true)
    assert.equal(Object.hasOwn(q, '_answered'), false)
  })

  test(`${pkg}: custom answer key and truthy ordinary answers keep existing semantics`, () => {
    const { adapter } = loadAdapter(pkg)
    const q = { id: 3, schedule_id: 17, question_type: 'single_choice' }
    assert.equal(adapter.isQuestionAnswered(q, { 17: ' ' }, 'schedule_id'), true)
    assert.deepEqual(plain(adapter.buildAnsweredFlags([q], { 17: 'A' }, 'schedule_id')), { 17: true })
  })

  test(`${pkg}: serialization uses group order and IDs rather than answer-map order`, () => {
    const { adapter } = loadAdapter(pkg)
    const groups = [{ marker: '2' }, { blank_id: '1' }]
    assert.equal(adapter.serializeBlankAnswer(groups, { 1: ' b ', 2: ' a ' }), '2:A;1:B')
    assert.equal(Object.hasOwn(groups[0], 'id'), false)
  })

  for (const [type, correct, user, expected] of [
    ['single_choice', 'A', 'a', true],
    ['single_choice', 'A', 'B', false],
    ['multiple_choice', 'AB', 'BA', true],
    ['true_false', 'true', '对', true],
    ['single_choice', '', 'A', null],
    ['single_choice', 'A', '', null],
  ]) {
    test(`${pkg}: ${type} correctness ${JSON.stringify([correct, user])}`, () => {
      const q = { question_type: type, answer: correct }
      assert.equal(loadAdapter(pkg).adapter.isAnswerCorrect(q, user), expected)
    })
  }

  test(`${pkg}: ungrouped legacy blank choice keeps its single-choice fallback`, () => {
    const { adapter } = loadAdapter(pkg)
    const q = { question_type: 'multi_blank_choice', answer: 'B', options: { A: 'one', B: 'two' } }
    assert.equal(adapter.isAnswerCorrect(q, 'b'), true)
    assert.equal(adapter.isAnswerCorrect(q, 'a'), false)
  })

  test(`${pkg}: editable option flags follow multi-choice selection without sorting keys`, () => {
    const { adapter } = loadAdapter(pkg)
    const q = { id: 9, question_type: 'multiple_choice', _optionKeys: ['B', 'A'],
      _opts: { A: 'alpha', B: 'beta' } }
    const list = adapter.buildOptionList(q, { 9: 'BA' })
    assert.deepEqual(Array.from(list, opt => [opt.key, opt._selected]), [['B', true], ['A', true]])
  })

  test(`${pkg}: readonly options copy image segments and retain nested references`, () => {
    const { adapter } = loadAdapter(pkg)
    const metadata = { marker: true }, segment = { type: 'image', url: '/choice.png', metadata }
    const options = { A: { text: 'alpha', segments: [segment] }, B: 'beta' }
    const q = { question_type: 'multiple_choice' }
    const list = adapter.buildOptionListReadonly(q, options, ['B', 'A'], 'AB', 'A')
    assert.deepEqual(Array.from(list, opt => [opt.key, opt._isCorrect, opt._isUserAnswer, opt._isBoth]),
      [['B', true, false, false], ['A', true, true, true]])
    assert.notEqual(list[1]._segments[0], segment)
    assert.equal(list[1]._segments[0].metadata, metadata)
    assert.equal(segment.url, '/choice.png')
    assert.equal(list[1]._needsRich, false)
  })
}

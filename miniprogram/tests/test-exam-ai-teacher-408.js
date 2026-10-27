const assert = require('node:assert/strict')
const { test: nodeTest } = require('node:test')
const path = require('node:path')

for (const pkg of ['study', 'exam']) {
const teacher = require(pkg === 'study' && process.env.STUDY_RESULT_BASELINE
  ? path.join(process.env.STUDY_RESULT_BASELINE, 'ai-teacher-408.js')
  : `../subpackages/${pkg}/utils/ai-teacher-408`)
const test = (name, ...args) => nodeTest(`${pkg}: ${name}`, ...args)

test('teacher retains exports and the complete empty result shape and text', () => {
  assert.deepEqual(Object.keys(teacher), [
    'ACTIONS', 'PRIMARY_ACTIONS', 'MORE_ACTIONS', 'ACTION_BY_KEY',
    'normalizeResult', 'errorMessage', 'submitFeedback',
  ])
  assert.deepEqual(teacher.normalizeResult({}), {
    action: '', actionLabel: 'AI 老师', title: 'AI 老师', summary: '', sections: [],
    knowledgePoints: [], practiceQuestion: null, nextAction: null, fromFallback: false,
    personalization: {}, promptVersion: '',
  })
  assert.equal(teacher.ACTIONS.length, 7)
  assert.deepEqual(teacher.PRIMARY_ACTIONS.map(item => item.action), [
    'explain_options', 'core_concept', 'similar_question', 'connect_knowledge',
  ])
})

test('input decoding rejects primitives and accepts fenced JSON and historical wrappers', () => {
  for (const value of [null, undefined, false, 1, [], '', 'invalid', '[]', 'null']) {
    assert.equal(teacher.normalizeResult(value), null)
  }
  assert.equal(teacher.normalizeResult('```json\n{"action":"core_concept"}\n```').action, 'core_concept')
  assert.equal(teacher.normalizeResult('prefix {"title":" hi "} suffix').title, 'hi')
  assert.equal(teacher.normalizeResult({ result: { data: { title: 'inner' } } }).title, 'inner')
  assert.equal(teacher.normalizeResult({ data: { title: 'inner' }, action: 'outer' }).action, 'outer')
  assert.equal(teacher.normalizeResult({ data: { title: 'inner' }, sections: [] }).title, 'AI 老师')
  assert.notEqual(teacher.normalizeResult({ result: [] }), null)
})

test('summary groups and section traversal preserve aliases, order, deduplication and keys', () => {
  const result = teacher.normalizeResult({
    summary: { analysis: ' explain ', diagnosis: ' why ', suggestion: [' next '] },
    sections: [
      { heading: ' extra ', points: [' a ', 'b'] },
      { heading: 'extra', points: ['a', 'b'] },
    ],
  })
  assert.equal(result.summary, 'why')
  assert.deepEqual(result.sections, [
    { key: '0-错因诊断', heading: '错因诊断', points: ['why'] },
    { key: '1-复练建议', heading: '复练建议', points: ['next'] },
    { key: '2-题目解析', heading: '题目解析', points: ['explain'] },
    { key: '3-extra', heading: 'extra', points: ['a', 'b'] },
  ])
  const aliases = teacher.normalizeResult({ summary: { mistake_diagnosis: 0, diagnosis: 'later' } })
  assert.equal(aliases.summary, '0')
  assert.equal(teacher.normalizeResult({ summary: '{}' }).summary, '')
})

test('knowledge point projection preserves original indexes, limits and coercion', () => {
  const items = [null, ...Array.from({ length: 10 }, (_, index) => ({
    name: ` name${index} `, relation: index, mastery_hint: 0, masteryHint: 'fallback',
  }))]
  const result = teacher.normalizeResult({ knowledge_points: items })
  assert.equal(result.knowledgePoints.length, 8)
  assert.deepEqual(result.knowledgePoints[0], {
    key: '1-name0', name: 'name0', relation: '0', masteryHint: 'fallback',
  })
  const sections = Array.from({ length: 10 }, (_, i) => ({ heading: `h${i}`, points: [1, 2, 3, 4, 5, 6] }))
  const limited = teacher.normalizeResult({ sections }).sections
  assert.equal(limited.length, 8)
  assert.deepEqual(limited[0].points, ['1', '2', '3', '4', '5'])
})

test('practice projection preserves option enumeration, falsy values and alias precedence', () => {
  const result = teacher.normalizeResult({
    practice_question: {
      stem: ' stem ', options: { b: ' B ', 2: 0, 1: false, a: null, c: ' ' },
      answer: false, analysis: 0, difficulty_delta: 0, difficultyDelta: 2,
    },
    practiceQuestion: { stem: 'ignored' },
  }).practiceQuestion
  assert.deepEqual(result, {
    stem: 'stem', options: [
      { key: '1', text: 'false' }, { key: '2', text: '0' }, { key: 'b', text: 'B' },
    ],
    answer: 'false', analysis: '0', difficultyDelta: 0,
  })
  assert.equal(teacher.normalizeResult({ practice_question: 'truthy', practiceQuestion: {} }).practiceQuestion, null)
  assert.deepEqual(teacher.normalizeResult({ practiceQuestion: [] }).practiceQuestion.options, [])
  for (const [raw, expected] of [['-2', -2], ['bad', 0], [Infinity, Infinity], [false, 0]]) {
    assert.equal(teacher.normalizeResult({ practiceQuestion: { difficultyDelta: raw } })
      .practiceQuestion.difficultyDelta, expected)
  }
})

test('practice option getters keep repeated reads and precede field coercion and action lookup', () => {
  const events = []
  let reads = 0
  const practice = {
    get options() {
      reads += 1
      events.push(`options${reads}`)
      return reads < 4 ? { b: 'unused', a: 'unused' } : { b: ' B1 ', a: ' A2 ' }
    },
    get stem() { events.push('stem'); return 's' },
    get answer() { events.push('answer'); return 'a' },
    get analysis() { events.push('analysis'); return 'p' },
    get difficulty_delta() { events.push('difficulty'); return 1 },
  }
  const source = {
    get knowledge_points() { events.push('knowledge'); return [] },
    get practice_question() { events.push('practice'); return practice },
    get practiceQuestion() { throw new Error('unexpected alias read') },
    get action() { events.push('action'); return 'core_concept' },
  }
  assert.deepEqual(teacher.normalizeResult(source).practiceQuestion.options,
    [{ key: 'b', text: 'B1' }, { key: 'a', text: 'A2' }])
  assert.deepEqual(events, [
    'knowledge', 'knowledge', 'practice', 'options1', 'options2', 'options3',
    'options4', 'options5', 'stem', 'answer', 'analysis', 'difficulty', 'action',
  ])
})

test('practice coercion and getter failures propagate unchanged before action lookup', () => {
  const failure = new Error('practice failure')
  for (const practice of [
    { get options() { throw failure } },
    { stem: { toString() { throw failure } } },
    { difficulty_delta: { valueOf() { throw failure } } },
  ]) {
    const source = {
      practice_question: practice,
      get action() { throw new Error('action read too early') },
    }
    assert.throws(() => teacher.normalizeResult(source), error => error === failure)
  }
})

test('result aliases retain truthiness, nullish precedence and referenced objects', () => {
  const next = [], personalization = []
  const result = teacher.normalizeResult({
    action: 'core_concept', action_label: 0, actionLabel: ' custom ',
    next_action: next, nextAction: { ignored: true }, personalization,
    from_fallback: false, fromFallback: true, prompt_version: 0, promptVersion: ' v2 ',
  })
  assert.equal(result.actionLabel, 'custom')
  assert.equal(result.title, '这道题真正考什么')
  assert.equal(result.nextAction, next)
  assert.equal(result.personalization, personalization)
  assert.equal(result.fromFallback, false)
  assert.equal(result.promptVersion, 'v2')
})

test('action metadata mutation is observed while replacing its exported object stays local', t => {
  const metadata = teacher.ACTION_BY_KEY, oldLabel = metadata.core_concept.label
  t.after(() => { teacher.ACTION_BY_KEY = metadata; metadata.core_concept.label = oldLabel })
  metadata.core_concept.label = 'patched label'
  assert.equal(teacher.normalizeResult({ action: 'core_concept' }).title, 'patched label')
  teacher.ACTION_BY_KEY = {}
  assert.equal(teacher.normalizeResult({ action: 'core_concept' }).title, 'patched label')
})

test('error text and feedback retain receiver, payload, coercion and rejected error identity', async () => {
  const failure = new Error('network')
  const api = {
    getErrorMessage(error) { assert.equal(this, api); assert.equal(error, failure); return 'exam_in_progress_ai_blocked' },
    async post(url, payload) {
      assert.equal(this, api)
      assert.equal(url, '/ai/feedback')
      assert.deepEqual(payload, {
        source: '408_teacher', feedback_type: 'like', question_id: 4,
        detail: 'action=core_concept;prompt_version=v1;fallback=0',
      })
      throw failure
    },
  }
  assert.equal(teacher.errorMessage(failure, api), '考试进行中不开放答案型 AI 讲解，请交卷后再使用。')
  assert.equal(teacher.errorMessage(null), 'AI 老师暂不可用，请稍后重试')
  assert.equal(await teacher.submitFeedback({}, {}), false)
  await assert.rejects(teacher.submitFeedback(api, {
    questionId: '4', feedbackType: 'like', result: { action: 'core_concept', promptVersion: 'v1' },
  }), error => error === failure)
})
}

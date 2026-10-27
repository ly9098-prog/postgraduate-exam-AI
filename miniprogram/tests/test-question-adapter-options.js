const assert = require('node:assert/strict')
const { test } = require('node:test')
const { loadAdapter, plain } = require('./question-adapter-support')

for (const pkg of ['study', 'exam']) {
  for (const [name, input, expected] of [
    ['empty', null, []],
    ['invalid JSON', '{invalid', []],
    ['array', ['first', 0], [{ key: 'A', text: 'first' }, { key: 'B', text: '0' }]],
    ['map', { B: 'second', A: 'first' }, [{ key: 'B', text: 'second' }, { key: 'A', text: 'first' }]],
    ['JSON wrapper', '{"options":{"D":"fourth"}}', [{ key: 'D', text: 'fourth' }]],
    ['record', { option_key: ' X ', value: 'value' }, [{ option_key: ' X ', value: 'value', key: 'X', text: 'value' }]],
    ['field fallback', [{ code: 'VII', text: '', content: 'body' }],
      [{ code: 'VII', text: 'body', content: 'body', key: 'VII' }]],
  ]) {
    test(`${pkg}: normalizes ${name} without sorting options`, () => {
      assert.deepEqual(plain(loadAdapter(pkg).adapter.normalizeBlankOptionList(input)), expected)
    })
  }

  test(`${pkg}: option copies retain nested metadata and segment rendering`, () => {
    const nested = { marker: true }
    const segments = [{ type: 'text', text: 'segment' }]
    const input = [{ key: 'C', text: 'ignored', segments, metadata: nested }]
    const { adapter } = loadAdapter(pkg)
    const result = adapter.normalizeBlankOptionList(input)
    assert.notEqual(result[0], input[0])
    assert.equal(result[0].segments, segments)
    assert.equal(result[0].metadata, nested)
    assert.equal(result[0].text, 'segment')
    assert.equal(input[0].text, 'ignored')
  })

  for (const [stem, content, expected] of [
    ['① and ②', {}, ['①', '②']],
    ['(一) and （二）', {}, ['1', '2']],
    ['( ) and （ ）', {}, ['1', '2']],
    ['___ and ＿＿', {}, ['1', '2']],
    ['no markers', { blank_count: 3 }, ['1', '2', '3']],
    ['① and ②', { blank_ids: ['x', 'x', ' y '] }, ['x', 'y']],
  ]) {
    test(`${pkg}: flat options infer blank IDs from ${JSON.stringify(content)} ${stem}`, () => {
      const q = { question_type: 'multi_blank_choice', content: { text: stem, ...content },
        options: { A: 'one', B: 'two' } }
      const groups = loadAdapter(pkg).adapter.getBlankOptionGroups(q)
      assert.deepEqual(Array.from(groups, group => group.id), expected)
      assert.notEqual(groups[0].options, groups[1].options)
      assert.notEqual(groups[0].options[0], groups[1].options[0])
    })
  }

  test(`${pkg}: content groups precede question groups and ordinary options`, () => {
    const source = { id: 'slot', options: { A: 'one' }, metadata: { marker: true } }
    const q = { content: { blank_option_groups: [source] },
      blank_option_groups: [{ id: 'ignored', options: ['two'] }], options: { B: 'ordinary' } }
    const { adapter } = loadAdapter(pkg)
    const groups = adapter.getBlankOptionGroups(q)
    assert.equal(groups[0].id, 'slot')
    assert.notEqual(groups[0], source)
    assert.equal(groups[0].options, source.options)
    assert.equal(groups[0].metadata, source.metadata)
    assert.equal(adapter.getQuestionOptions(q), q.options)
  })

  test(`${pkg}: grouped dictionaries are not mistaken for ordinary option maps`, () => {
    const q = { content: '{"options":{"1":{"A":"one"},"2":{"B":"two"}}}' }
    const { adapter } = loadAdapter(pkg)
    assert.equal(adapter.getQuestionOptions(q), null)
    const groups = adapter.getBlankOptionGroups(q)
    assert.deepEqual(Array.from(groups, group => group.id), ['1', '2'])
    assert.deepEqual(plain(groups[0].options), { A: 'one' })
    assert.deepEqual(plain(groups[1].options), { B: 'two' })
  })

  test(`${pkg}: a single inferred blank does not expand flat options into groups`, () => {
    const q = { question_type: 'multi_blank_choice', content: { text: '___' }, options: { A: 'one' } }
    const { adapter } = loadAdapter(pkg)
    assert.deepEqual(plain(adapter.getBlankOptionGroups(q)), [])
    assert.equal(adapter.getQuestionOptions(q), q.options)
  })
}

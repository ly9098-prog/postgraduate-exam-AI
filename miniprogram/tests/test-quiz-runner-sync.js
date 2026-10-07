/* Native study/exam runner parity and atomic view-layer updates. No network. */
const assert = require('assert')
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const root = path.resolve(__dirname, '..')
const read = file => fs.readFileSync(path.join(root, file), 'utf8')
const dirs = ['study', 'exam'].map(pkg => `subpackages/${pkg}/components/quiz-runner/`)
for (const file of ['quiz-runner.js', 'quiz-runner.wxml', 'quiz-runner.wxss', 'practice-theme.wxss']) {
  assert.strictEqual(read(dirs[0] + file), read(dirs[1] + file), file + ' remains in sync')
}
for (const pkg of ['study', 'exam']) {
  const dir = `subpackages/${pkg}/components/quiz-runner/`
  const js = read(dir + 'quiz-runner.js')
  const wxml = read(dir + 'quiz-runner.wxml')
  const css = read(dir + 'quiz-runner.wxss') + read(dir + 'practice-theme.wxss')
  assert.ok(!/heroCollaps|expandHero|runner-collapsed|hero-collapsed/.test(js + wxml + css), pkg + ' removes all collapse behavior and styles')
  assert.ok(css.includes('.runner-reference .runner-mark-btn.runner-marked{color:#23483C;border-color:#8DCBB7;background:#B7EBD9}'), 'marked button overrides the legacy neon border explicitly')
  assert.ok(!/nodes=\"{{currentQuestion\./.test(wxml), 'template does not bind rendered nodes to the parent question directly')
  const navTemplate = wxml.slice(wxml.indexOf('<template name="runner-navigation">'), wxml.indexOf('</template>', wxml.indexOf('<template name="runner-navigation">')))
  assert.strictEqual((navTemplate.match(/class="runner-nav-btn runner-primary-action/g) || []).length, 1, 'next/final uses one stable action node')
  const primaryOpening = navTemplate.match(/<view[\s\S]*?runner-primary-action[\s\S]*?>/)
  assert.ok(primaryOpening && !/wx:if/.test(primaryOpening[0]), 'action node is never destroyed during a question switch')
  assert.ok(wxml.includes('bindtap="onPrimaryNavigation"'), 'primary action delegates without replacing its node')
  assert.ok(js.includes('onPrimaryNavigation: function'), 'primary action tap handler exists')
  const navShell = wxml.slice(0, wxml.indexOf('</template>'))
  assert.ok(!navShell.includes('_animating'), 'navigation shell does not visually react to transient animation lock')
  assert.strictEqual((wxml.match(/wx:for="{{\[_displayQuestion\]}}" wx:key="id"/g) || []).length, 2, 'CODE and MIXED remount on question identity, resetting horizontal code scroll')
  const config = JSON.parse(read(dir + 'quiz-runner.json'))
  assert.ok(Object.values(config.usingComponents).every(p => p.startsWith(`/subpackages/${pkg}/`)), 'component dependencies stay in their own package')
  let definition
  const old = global.Component
  global.Component = value => { definition = value }
  try { require(path.join(root, dir, 'quiz-runner.js')) } finally { global.Component = old }
  const data = Object.assign({}, definition.data)
  for (const [key, prop] of Object.entries(definition.properties)) data[key] = prop.value
  Object.assign(data, { mode: pkg === 'exam' ? 'exam' : 'practice', totalCount: 3, currentIndex: 0 })
  const writes = [], events = []
  const target = Object.assign({ data, setData(patch, cb) { writes.push(patch); Object.assign(data, patch); if (cb) cb() }, triggerEvent(name, detail) { events.push({ name, detail }) } }, definition.methods)
  definition.created.call(target)
  const originalGoNext = target.goNext
  const originalOnSubmit = target.onSubmit
  let primaryAction = ''
  target.goNext = () => { primaryAction = 'next' }
  target.onSubmit = () => { primaryAction = 'submit' }
  target.onPrimaryNavigation()
  assert.strictEqual(primaryAction, 'next', 'primary action advances before final question')
  data.currentIndex = 2
  target.onPrimaryNavigation()
  assert.strictEqual(primaryAction, 'submit', 'primary action submits on final question')
  target.goNext = originalGoNext
  target.onSubmit = originalOnSubmit
  data.currentIndex = 0
  const q = id => ({ id, question_type: 'single_choice', _renderModel: { mode: 'RICH_TEXT', richTextNodes: [{ type: 'text', text: 'Question ' + id }] } })
  const observe = definition.observers['currentQuestion, answerState']
  const first = q(1), second = q(2)
  data.currentQuestion = first
  observe.call(target, first, { questionId: 1, optionList: [{ key: 'A', _text: 'first' }] })
  target.onQuestionScroll({ detail: { scrollTop: 300 } })
  assert.ok(!Object.hasOwn(data, 'heroCollapsed'))
  target._switchTargetIndex = 1
  target._switchDirection = 'left'
  data.currentIndex = 1
  data.currentQuestion = second
  assert.strictEqual(data._displayQuestion.id, 1, 'parent property changing does not paint the new stem prematurely')
  writes.length = 0
  observe.call(target, second, { questionId: 2, optionList: [{ key: 'B', _text: 'second' }] })
  assert.strictEqual(writes.length, 1)
  assert.strictEqual(writes[0]._displayQuestion.id, 2)
  assert.strictEqual(writes[0]._optionList[0]._text, 'second')
  assert.strictEqual(writes[0].animClass, 'slide-in-left')
  assert.strictEqual(writes[0].questionScrollIntoView, 'runner-scroll-top-anchor', 'long-question scroll reset belongs to the same view commit')
  data._animating = true
  target.toggleMark(); target.onSubmit(); target.onMaster(); target.selectOption({ currentTarget: { dataset: { option: 'B' } } })
  assert.strictEqual(events.length, 0, 'no answer, mark, master, or submit can target a half-switched question')
  target.onQuestionAnimationEnd({ detail: { animationName: 'runnerQuestionInLeft' } })
  target.toggleMark()
  assert.strictEqual(events.pop().name, 'togglemark')
  data.readonly = true
  target.toggleMark(); target.selectOption({ currentTarget: { dataset: { option: 'B' } } })
  assert.strictEqual(events.length, 0, 'expired/read-only exam remains protected')
  data.readonly = false
  data.submitted = true
  target.onSubmit()
  assert.strictEqual(events.length, 0, 'accepted submission cannot be resubmitted')
  definition.lifetimes.detached.call(target)
  console.log(pkg + ' snapshot, long-scroll, motion and action guards passed')
}
// The exam view builder must supply the exact payload consumed by the runner.
assert.strictEqual(read('subpackages/study/utils/stem-render.js'), read('subpackages/exam/utils/stem-render.js'), 'render contracts are synchronized without crossing package boundaries')
const examView = require('../subpackages/exam/utils/exam-runner-view')
const plain = examView.buildRenderView({ id: 9901, content: { text: '普通考试题干必须可见' }, options: { A: '选项甲', B: '选项乙' } })
assert.strictEqual(plain.question._renderModel.mode, 'RICH_TEXT')
assert.ok(plain.question._renderModel.richTextNodes.length > 0, 'ordinary exam stems have rich-text nodes, not an empty plainText-only payload')
assert.ok(JSON.stringify(plain.question._renderModel.richTextNodes).includes('普通考试题干必须可见'))
const code = examView.buildRenderView({ id: 9902, content: { text: 'void f() {\n  int x = 1;\n  return;\n}' }, options: { A: '1', B: '2' } })
assert.strictEqual(code.question._renderModel.mode, 'CODE')
assert.ok(code.question._renderModel.rawText.includes('  int x'))
assert.strictEqual(code.question._renderModel.richTextNodes.length, 0)
assert.strictEqual(code.question._renderModel.html, '')
const structured = examView.buildRenderView({ id: 9903, content: { text: '请判断下面代码的结果', render_mode: 'segments', segments: [{ type: 'text', text: '请判断下面代码的结果' }, { type: 'code', code: '  return 1;' }] }, options: { A: '1', B: '2' } })
assert.strictEqual(structured.question._renderModel.mode, 'SEGMENTS', 'prose plus valid code segments must not discard the code')
assert.ok(structured.question._renderModel.segments.some(segment => segment.type === 'code'))
const icon = read('assets/icons/practice/notebook-tabs.svg')
assert.ok(icon.includes('stroke="#3A6F5B"') && icon.includes('viewBox="0 0 24 24"'))
assert.ok(read('assets/icons/practice/README.md').includes('lucide-icons/lucide/main/icons/notebook-tabs.svg'))
assert.ok(read('subpackages/exam/exam-runner/index.wxml').includes('navigationBarHeight="{{navBarHeight}}"'))
if (process.argv[2]) {
  const context = { window: { __webview_engine_version__: 0.02 }, console }
  vm.createContext(context)
  vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context)
  const all = n => [n, ...(n.children || []).flatMap(c => c && typeof c === 'object' ? all(c) : [])]
  const byClass = (t, cls) => all(t).filter(n => ((n.attr || {}).class || '').split(/\s+/).includes(cls))
  for (const dir of dirs) {
    const render = context.$gwx(dir + 'quiz-runner.wxml')
    const base = { mode: dir.includes('/exam/') ? 'exam' : 'practice', theme: 'default', totalCount: 3, currentIndex: 2, showSubmitButton: true, showNavigation: true, showMarkButton: true, subjectName: 'Long paper title', elapsedText: '01:20:30', customNavigation: true, navigationBarHeight: 40, _qTypeLabel: '单选题', _optionList: [] }
    for (const mode of ['SEGMENTS', 'RICH_TEXT', 'CODE', 'LATEX', 'MIXED']) {
      const q = { id: 5, _renderModel: { mode, richTextNodes: [], rawText: '  x++;', html: '<p>x</p>', segments: [] } }
      const t = render(Object.assign({}, base, { _displayQuestion: q, _codeLines: [{ no: 1, text: '  x++;' }], _mixedBlocks: [{ type: 'CODE', _codeLines: [{ no: 1, text: '  y++;' }] }] }))
      assert.strictEqual(byClass(t, 'runner-reference-hero').length, 1)
      assert.strictEqual(byClass(t, 'runner-final-submit').length, 1)
      assert.strictEqual(byClass(t, 'runner-question-motion').length, 1)
      assert.strictEqual(byClass(t, 'runner-mark-btn').length, 1)
      assert.strictEqual(byClass(t, 'runner-sheet-trigger-icon')[0].attr.src, '/assets/icons/practice/notebook-tabs.svg')
      if (mode === 'CODE' || mode === 'MIXED') assert.strictEqual(byClass(t, 'runner-code-wrapper').length, 1, 'native imported code template renders in its own package')
    }
    const empty = render(Object.assign({}, base, { totalCount: 0, _displayQuestion: null }))
    assert.strictEqual(byClass(empty, 'runner-final-submit').length, 0, 'empty runner cannot expose an enabled submit')
  }
  console.log('Compiled study/exam five-mode layouts and local code imports passed')
}
console.log('Study/exam runner sync regression passed')

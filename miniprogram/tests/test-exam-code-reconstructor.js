const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')
const { test } = require('node:test')

const directory = path.resolve(__dirname, '../subpackages')

function loadCode(subpackage) {
  const filename = path.join(directory, subpackage, 'utils/code-reconstructor.js')
  const logs = []
  const modules = new Map()
  const context = vm.createContext({ console: { log: (...args) => logs.push(args) } })
  function load(file) {
    if (modules.has(file)) return modules.get(file).exports
    const module = { exports: {} }
    modules.set(file, module)
    const localRequire = createRequire(file)
    const factory = vm.runInContext(
      '(function(require,module,exports){\n' + fs.readFileSync(file, 'utf8') + '\n})',
      context, { filename: file })
    factory(request => {
      assert.ok(request.startsWith('./'), 'code helpers must stay in their subpackage')
      return load(localRequire.resolve(request))
    }, module, module.exports)
    return module.exports
  }
  return { code: load(filename), logs }
}

function plain(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

test('exam code API retains export names and arities', () => {
  const { code } = loadCode('exam')
  assert.deepEqual(Object.keys(code), [
    'reconstructCode', 'containsCode', 'shouldReconstructCode',
    'sanitizeImportedCodeArtifacts', 'detectCodeLanguageHint', 'detectDollarArtifactPattern',
  ])
  assert.deepEqual(Object.values(code).map(fn => fn.length), [2, 1, 1, 1, 1, 1])
})

for (const [text, language] of [
  ['<?php echo $item;', 'php'],
  ['$_POST["id"]', 'php'],
  ['#!/bin/sh\necho ${HOME}', 'shell'],
  ['${value}', 'js'],
  ['@items %lookup', 'perl'],
  ['@items $value', 'perl'],
  ['const $item = `value`;', 'js'],
  ['printf("value");', 'c-like'],
  ['if (x) { return x; }', 'c-like'],
  ['a sentence', 'unknown'],
]) {
  test('language guard: ' + language + ' ' + text, () => {
    assert.equal(loadCode('exam').code.detectCodeLanguageHint(text), language)
  })
}

test('reconstruction keeps thresholds, for-header semicolons and option order', () => {
  const { code } = loadCode('exam')
  assert.equal(code.containsCode('return'), false)
  assert.equal(code.containsCode('LinkList'), false)
  assert.equal(code.containsCode('LinkList;'), true)
  assert.equal(code.shouldReconstructCode('int x; return x;'), true)
  assert.equal(code.shouldReconstructCode('for (int i=0; i<2; i++) {}'), false)
  assert.equal(code.shouldReconstructCode('int x;\nreturn x;\n'), false)
  const text = 'int x;return x;'
  assert.equal(code.reconstructCode(text), 'int x;\nreturn x;')
  const events = []
  const options = Object.fromEntries(['fixOperators', 'fixStructure', 'fixIndent'].map(key =>
    [key, false]))
  const proxy = new Proxy(options, { get(target, key) {
    events.push(key)
    return target[key]
  } })
  assert.equal(code.reconstructCode(text, proxy), text)
  assert.deepEqual(events, ['fixOperators', 'fixStructure', 'fixIndent'])
  assert.equal(code.reconstructCode('', proxy), '')
  assert.deepEqual(events, ['fixOperators', 'fixStructure', 'fixIndent'])
})

test('artifact cleanup preserves comments, single quotes and escaped dollar controls', () => {
  const { code, logs } = loadCode('exam')
  const input = 'int main() { $\n// "$\\n"\n/* "$\\t" */\n' +
    "char c = '$\\n';\n" + 'printf("$\\n$\\t$\\r\\\\n"); $\n}'
  const expected = 'int main() {\n// "$\\n"\n/* "$\\t" */\n' +
    "char c = '$\\n';\n" + 'printf("\\n\\t\\r\\\\n");\n}'
  assert.equal(code.sanitizeImportedCodeArtifacts(input), expected)
  assert.deepEqual(plain(logs), [['[CODE_ARTIFACT_SANITIZE]', {
    removedDollarCount: 5,
    language: 'c-like',
    reasons: ['TRAILING_AFTER_BRACE_SEMICOLON:2'],
  }]])
})

for (const input of ['', 'ordinary prose', 'int x;return x;']) {
  for (const failed of ['fixOperators', 'fixStructure', 'fixIndent']) {
    test('option getter failure at ' + failed + ': ' + JSON.stringify(input), () => {
      const { code } = loadCode('exam')
      const events = []
      const error = new Error(failed)
      const options = new Proxy({}, { get(_target, key) {
        events.push(key)
        if (key === failed) throw error
      } })
      if (!input) {
        assert.equal(code.reconstructCode(input, options), input)
        assert.deepEqual(events, [])
      } else {
        assert.throws(() => code.reconstructCode(input, options), caught => caught === error)
        const order = ['fixOperators', 'fixStructure', 'fixIndent']
        assert.deepEqual(events, order.slice(0, order.indexOf(failed) + 1))
      }
    })
  }
}

test('artifact classification retains reason order and trailing-dollar thresholds', () => {
  const { code } = loadCode('exam')
  assert.deepEqual(plain(code.detectDollarArtifactPattern('}; $\n$\nabc$\n')), {
    isLikelyArtifact: true,
    hasTrailingDollarArtifact: true,
    reasons: [
      'TRAILING_AFTER_BRACE_SEMICOLON:1', 'STANDALONE_LINE:1',
      'MULTI_LINE_TRAILING_DOLLAR:3',
    ],
  })
  assert.equal(code.detectDollarArtifactPattern('abc$\ndef$').isLikelyArtifact, false)
  assert.equal(code.sanitizeImportedCodeArtifacts('<?php\n}; $'), '<?php\n}; $')
  assert.equal(code.sanitizeImportedCodeArtifacts('#!/bin/sh\necho x; $'),
    '#!/bin/sh\necho x; $')
  assert.equal(code.sanitizeImportedCodeArtifacts('@items %lookup\n}; $'),
    '@items %lookup\n}; $')
})

test('exam and study preserve results, errors and log payloads across code corpus', () => {
  const exam = loadCode('exam')
  const study = loadCode('study')
  const fragments = [
    '', 'int main(){', 'for(int i=0;i<2;i++){', 'printf("a;$\\\\n");',
    'return x;', '}$', '}; $', '$', 'abc$', '/* "$\\n" */', '// "$\\n"',
    "'$\\t'", '"$\\n"', '"unterminated$\\r', '"escaped\\"$\\n"',
    '#include <stdio.h>', '<?php', '#!/bin/sh\necho ${x}', '@a %b',
    'const $x=`${x}`;', 'LinkList L;', 'x + +; x * = 2;', 'if(x){',
    '/* unterminated', 'for(i=0;i<3;i++)x++;', 'x\\$', '\\\\', '}\nelse{',
  ]
  const values = [null, undefined, false, true, 0, 42, {}, [], ['return', ';', '{}']]
  for (let i = 0; i < fragments.length; i++) {
    for (let j = 0; j < fragments.length; j++) {
      values.push(fragments[i] + (j % 2 ? '\n' : ' ') + fragments[j])
    }
  }
  function outcome(fn, value, options) {
    try { return { value: plain(fn(value, options)) } } catch (error) {
      return { error: [error.name, error.message] }
    }
  }
  for (const value of values) {
    for (const name of Object.keys(exam.code)) {
      const options = name === 'reconstructCode' ? { fixOperators: false } : undefined
      assert.deepEqual(outcome(exam.code[name], value, options),
        outcome(study.code[name], value, options), name + ': ' + JSON.stringify(value))
      if (name === 'reconstructCode') {
        assert.deepEqual(outcome(exam.code[name], value), outcome(study.code[name], value))
        assert.deepEqual(outcome(exam.code[name], value, { fixStructure: false }),
          outcome(study.code[name], value, { fixStructure: false }))
      }
    }
  }
  assert.deepEqual(plain(exam.logs), plain(study.logs))
})

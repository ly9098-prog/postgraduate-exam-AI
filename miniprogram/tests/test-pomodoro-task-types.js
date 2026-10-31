const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const vm = require('node:vm')

const filename = path.join(__dirname, '../utils/pomodoro-task-types.js')
const source = fs.readFileSync(filename, 'utf8')
// CommonJS accepts duplicate functions that the WeChat Babel compiler rejects.
const syntax = spawnSync(process.execPath, ['--input-type=module', '--check'], {
  input: source,
  encoding: 'utf8',
})
assert.equal(syntax.status, 0, syntax.stderr)

const records = new Map()
const context = {
  module: { exports: {} },
  require(name) {
    assert.equal(name, './storage-core')
    return {
      get: key => records.get(key),
      set: (key, value) => records.set(key, value),
    }
  },
}
vm.runInNewContext(source, context, { filename })
const { pomodoroTaskTypes: types } = context.module.exports

assert.equal(types.getSelected(), 'new_questions')
assert.equal(types.setSelected('review'), 'review')
assert.equal(types.getSelected(), 'review')
assert.equal(types.label('review'), '复习')
assert.equal(types.setSelected('invalid'), 'new_questions')
assert.equal(types.typeForSession({ id: 1 }), '')
types.recordSession({ id: 1, client_start_id: 'local-1' }, 'wrong_questions')
assert.equal(types.typeForSession({ id: 1 }), 'wrong_questions')
assert.equal(types.typeForSession({ clientStartId: 'local-1' }), 'wrong_questions')
assert.equal(types.labelForSession({ id: 1 }), '错题')
types.recordSession({ id: 1 }, '')
assert.equal(types.typeForSession({ id: 1 }), 'wrong_questions')
assert.equal(types.typeForSession({ id: 1, task_type: 'exam' }), 'exam')
types.recordSession({ id: 2 }, 'invalid')
assert.equal(types.typeForSession({ id: 2 }), '')
assert.equal(types.labelForSession(null), '')

console.log('Pomodoro task types: strict syntax and storage behavior passed')

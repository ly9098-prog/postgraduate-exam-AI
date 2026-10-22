const assert = require('node:assert/strict')
const {
  findRouteSubject,
  findLegacySubject,
  findSubjectById,
} = require('../pages/pomodoro/utils/subject-selection')

const aggregate = { id: 408, code: 'exam408', _isAggregate: true, _disabled: false }
const leaves = [
  { id: 1, code: 'data_structure', name: '数据结构' },
  { id: 2, code: 'computer_network', name: '计算机网络' },
]
const coreSubjects = [{}, {}, {}, {}]

assert.deepEqual(findRouteSubject({
  route: { subjectId: 408, subjectCode: '' },
  aggregate,
  leaves,
  coreSubjects,
}), {
  selectedSubjectId: 408,
  selectedSubject: aggregate,
  allocationMode: 'equal_408_core_v1',
})

assert.deepEqual(findRouteSubject({
  route: { subjectId: null, subjectCode: 'data_structure' },
  aggregate,
  leaves,
  coreSubjects,
}), {
  selectedSubjectId: 1,
  selectedSubject: leaves[0],
  allocationMode: 'single',
})

assert.equal(findRouteSubject({
  route: { subjectId: 408, subjectCode: '' },
  aggregate: { ...aggregate, _disabled: true },
  leaves,
  coreSubjects,
}), null)

assert.equal(findRouteSubject({
  route: { subjectId: 408, subjectCode: '' },
  aggregate,
  leaves,
  coreSubjects: [{}, {}],
}), null)

assert.deepEqual(findRouteSubject({
  route: { subjectId: 1, subjectCode: 'data_structure' },
  aggregate,
  leaves,
  coreSubjects,
}), {
  selectedSubjectId: 1,
  selectedSubject: leaves[0],
  allocationMode: 'single',
}, 'subject_id wins over subject_code')

assert.deepEqual(findRouteSubject({
  route: { subjectId: null, subjectCode: 'exam408' },
  aggregate,
  leaves,
  coreSubjects,
}), {
  selectedSubjectId: 408,
  selectedSubject: aggregate,
  allocationMode: 'equal_408_core_v1',
})

assert.equal(findRouteSubject({
  route: { subjectId: 99, subjectCode: 'data_structure' },
  aggregate,
  leaves,
  coreSubjects,
}), null, 'a present but unmatched subject_id does not fall back to code')

assert.deepEqual(findRouteSubject({
  route: { subjectId: '408', subjectCode: '' },
  aggregate,
  leaves,
  coreSubjects,
}), {
  selectedSubjectId: 408,
  selectedSubject: aggregate,
  allocationMode: 'equal_408_core_v1',
})

assert.equal(findRouteSubject({
  route: { subjectId: null, subjectCode: '' },
  aggregate,
  leaves,
  coreSubjects,
}), null)

assert.deepEqual(findLegacySubject({ id: null, code: 'computer_network' }, leaves), {
  selectedSubjectId: 2,
  selectedSubject: leaves[1],
})
assert.equal(findLegacySubject({ id: 1, code: 'data_structure' }, leaves), null)
assert.equal(findLegacySubject(null, leaves), null)
assert.equal(findLegacySubject({ id: null, code: 'missing' }, leaves), null)
assert.deepEqual(findLegacySubject({ id: 0, code: 'data_structure' }, leaves), {
  selectedSubjectId: 1,
  selectedSubject: leaves[0],
})
assert.deepEqual(findLegacySubject({ id: null, code: 'data_structure' }, [
  { id: 9, code: 'data_structure' },
  { id: 1, code: 'data_structure' },
]), {
  selectedSubjectId: 9,
  selectedSubject: { id: 9, code: 'data_structure' },
})

assert.equal(findSubjectById(leaves, '2'), leaves[1])
assert.equal(findSubjectById(leaves, 2), leaves[1])
assert.equal(findSubjectById(leaves, '2abc'), null)
assert.equal(findSubjectById(leaves, 0), null)
assert.equal(findSubjectById(null, 2), null)
assert.equal(findSubjectById(leaves, 99), null)

const frozen = Object.freeze({
  route: Object.freeze({ subjectId: null, subjectCode: 'data_structure' }),
  aggregate: Object.freeze(aggregate),
  leaves: Object.freeze(leaves.map(Object.freeze)),
  coreSubjects: Object.freeze(coreSubjects.map(Object.freeze)),
})
assert.doesNotThrow(() => findRouteSubject(frozen))

console.log('Pomodoro subject selection passed: route/legacy/id lookup')

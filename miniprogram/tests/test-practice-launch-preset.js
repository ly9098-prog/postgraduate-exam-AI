const assert = require('node:assert/strict')
const { test } = require('node:test')
const {
  parseLaunchPreset,
  launchPresetOverrides,
  fastLaunchPresetView,
  resolvedLaunchPresetView,
  applyLaunchOverrides,
} = require('../subpackages/study/practice/utils/launch-preset')

const decode = value => (value == null ? '' : decodeURIComponent(String(value)))

test('parses and normalizes route launch options', () => {
  const preset = parseLaunchPreset({
    subject_id: 12,
    subject_code: ' data_structure ',
    mode: 'sequential',
    count: 88,
    knowledge_point: '%E6%A0%91',
    knowledge_point_id: 34,
    question_ids: '9,9,8,foo',
    allow_repeat: '1',
    autostart: '1',
    source: 'study-hub',
    plan_token: 'token',
    subject_name: '%E6%95%B0%E6%8D%AE%E7%BB%93%E6%9E%84',
    include_children: '1',
    include_descendants: '1',
    return_to: '/subpackages/study/knowledge-detail/index?id=1',
  }, decode)
  assert.deepEqual(preset, {
    subjectId: 12,
    mode: 'sequential',
    count: 50,
    knowledgePoint: '树',
    knowledgePointId: 34,
    questionIds: '',
    allowRepeat: true,
    autostart: true,
    source: 'study-hub',
    planToken: 'token',
    subjectName: '数据结构',
    includeChildren: true,
    includeDescendants: true,
    subjectCode: 'data_structure',
    returnTo: '/subpackages/study/knowledge-detail/index?id=1',
  })

  assert.equal(parseLaunchPreset({ return_to: '/pages/home/home' }, decode).returnTo, '')
  assert.equal(parseLaunchPreset(null, decode).subjectId, null)
})

test('targeted question IDs clear knowledge-point launch constraints', () => {
  const preset = parseLaunchPreset({
    subject_id: 12,
    question_ids: '9,8',
    mode: 'random',
    include_descendants: '1',
    knowledge_point_id: 34,
    allow_repeat: '0',
  }, decode)
  const overrides = launchPresetOverrides(preset)
  assert.deepEqual(overrides, {
    knowledgePoint: '',
    knowledgePointId: null,
    includeDescendants: false,
    questionIds: '9,8',
    allowRepeat: true,
    source: '',
    planToken: '',
    returnTo: '',
  })
  const target = {}
  applyLaunchOverrides(target, overrides)
  assert.deepEqual(target, {
    _launchKnowledgePoint: '',
    _launchKnowledgePointId: null,
    _launchIncludeDescendants: false,
    _launchQuestionIds: '9,8',
    _launchAllowRepeat: true,
    _launchSource: '',
    _launchPlanToken: '',
    _launchReturnTo: '',
  })
})

test('builds fast and resolved launch views with original fallback order', () => {
  const fastPreset = parseLaunchPreset({ subject_id: 12 }, decode)
  assert.deepEqual(fastLaunchPresetView(fastPreset, 'smart', 20), {
    mode: 'random',
    count: 20,
    selectedSubjectId: 12,
    selectedSubjectName: '专项练习',
    selectedSubjectHasChildren: false,
    expandedSubjectId: 12,
  })

  const resolvedPreset = parseLaunchPreset({ question_ids: '9,8' }, decode)
  const target = { subject_id: 12, display_name: '数据结构', has_children: true, parent_subject_id: 2 }
  assert.deepEqual(resolvedLaunchPresetView(resolvedPreset, target, 'sequential', 20), {
    mode: 'random',
    count: 2,
    selectedSubjectId: 12,
    selectedSubjectName: '数据结构',
    selectedSubjectHasChildren: true,
    expandedSubjectId: 2,
  })
})

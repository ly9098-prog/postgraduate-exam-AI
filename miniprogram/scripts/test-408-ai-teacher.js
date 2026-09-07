#!/usr/bin/env node
/* 408 专项 AI 老师静态回归：固定动作、固定版本、考试防泄题与三类复盘入口。 */
const fs = require('fs')
const path = require('path')
const assert = require('assert')

const miniRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(miniRoot, '..')
const backendRoot = path.join(repoRoot, 'backend')
const helper = require(path.join(miniRoot, 'utils/ai-teacher-408.js'))

const expectedActions = [
  'explain_correct',
  'explain_options',
  'core_concept',
  'similar_question',
  'harder_question',
  'connect_knowledge',
  'high_frequency_traps',
]
assert.deepStrictEqual(helper.ACTIONS.map(item => item.action), expectedActions, '408 AI 动作必须冻结为 7 个固定枚举')
assert.strictEqual(new Set(helper.ACTIONS.map(item => item.action)).size, 7, '固定动作不得重复')

const schema = fs.readFileSync(path.join(backendRoot, 'app/schemas/ai_teacher_408.py'), 'utf8')
const prompt = fs.readFileSync(path.join(backendRoot, 'app/ai/prompts_408_teacher.py'), 'utf8')
const service = fs.readFileSync(path.join(backendRoot, 'app/services/ai_teacher_408_service.py'), 'utf8')
const aiRoute = fs.readFileSync(path.join(backendRoot, 'app/api/v1/ai.py'), 'utf8')

assert(!/\bprompt\s*:/.test(schema), '客户端请求 schema 不得暴露自由 prompt 字段')
expectedActions.forEach(action => assert(prompt.includes(`"${action}"`), `服务端缺少固定动作 ${action}`))
assert(service.includes('QuestionVersion'), '408 AI 必须从题目历史版本加载事实')
assert(service.includes('question_version_id'), '408 AI 必须携带固定 question_version_id')
assert(service.includes('UserKnowledgeState'), '408 AI 必须接入用户 mastery/confidence')
assert(service.includes('WrongQuestionErrorDiagnosis'), '408 AI 必须接入近期错因')
assert(service.includes('KnowledgeEdge'), '408 AI 必须接入知识图谱邻居')
assert(service.includes('check_token_limit'), '408 AI 必须复用 token budget')
assert(service.includes('record_token_usage'), '408 AI 必须记录 AI usage')
assert(service.includes('owned_practice_record_id'), '历史 question_version_id 必须校验属于当前用户练习事实')
assert(service.indexOf('await record_token_usage(') < service.indexOf('parsed = _parse_json_object'), 'provider 成功后应先记 usage，再解析结构化输出')
assert(aiRoute.includes('@router.post("/feedback")'), '408 AI 必须保留 AI feedback 入口')
assert(service.includes('ExamAttempt.status == "in_progress"'), '408 AI 必须拦截进行中考试')
assert((aiRoute.match(/assert_ai_answer_access_allowed/g) || []).length >= 2, '旧 explain / analyze-mistake 端点必须同时受考试防泄题保护')
assert((aiRoute.match(/_get_wrong_question_for_answer_ai/g) || []).length >= 4, '旧错题 AI 生成/状态/恢复必须受考试防泄题保护')
assert(aiRoute.includes('active_exam_blocked_question_ids'), '批量 AI 预热必须跳过进行中考试题')
assert(aiRoute.includes('@router.post("/408-teacher"'), '缺少 408 teacher API')
assert(aiRoute.includes('@router.get("/408-teacher/actions"'), '缺少固定动作发现 API')

const surfaces = [
  {
    js: 'subpackages/study/wrong-detail/wrong-detail.js',
    wxml: 'subpackages/study/wrong-detail/wrong-detail.wxml',
    handler: 'run408TeacherAction',
    extra: 'diagnosis_id',
  },
  {
    js: 'subpackages/study/practice-result/index.js',
    wxml: 'subpackages/study/practice-result/index.wxml',
    handler: 'open408TeacherFromReview',
    extra: 'question_version_id',
  },
  {
    js: 'subpackages/exam/result/index.js',
    wxml: 'subpackages/exam/result/index.wxml',
    handler: 'open408Teacher',
    extra: 'exam_attempt_id',
  },
]

surfaces.forEach(surface => {
  const js = fs.readFileSync(path.join(miniRoot, surface.js), 'utf8')
  const wxml = fs.readFileSync(path.join(miniRoot, surface.wxml), 'utf8')
  assert(js.includes("api.post('/ai/408-teacher'"), `${surface.js} 未调用 408 teacher API`)
  assert(js.includes(surface.extra), `${surface.js} 未携带 ${surface.extra} 上下文`)
  assert(js.includes(`${surface.handler}(`), `${surface.js} 缺少 ${surface.handler}`)
  assert(wxml.includes(surface.handler), `${surface.wxml} 未绑定 ${surface.handler}`)
  assert(js.includes('feedback408Teacher('), `${surface.js} 缺少 AI 反馈处理`)
  assert(wxml.includes('feedback408Teacher'), `${surface.wxml} 未提供 AI 反馈入口`)
})

const examWxml = fs.readFileSync(path.join(miniRoot, 'subpackages/exam/result/index.wxml'), 'utf8')
assert(examWxml.includes('交卷后 408 专项 AI 老师'), '考试 AI 入口必须明确位于交卷后结果页')

const practiceJs = fs.readFileSync(path.join(miniRoot, 'subpackages/study/practice-result/index.js'), 'utf8')
const practiceWxml = fs.readFileSync(path.join(miniRoot, 'subpackages/study/practice-result/index.wxml'), 'utf8')
const examJs = fs.readFileSync(path.join(miniRoot, 'subpackages/exam/result/index.js'), 'utf8')
assert(practiceJs.includes('teacherActions: aiTeacher408.ACTIONS'), '普通练习结果页必须使用自定义 7 动作面板')
assert(examJs.includes('teacherActions: aiTeacher408.ACTIONS'), '考试结果页必须使用自定义 7 动作面板')
assert(practiceWxml.includes('select408TeacherAction'), '普通练习结果页缺少自定义动作选择处理')
assert(examWxml.includes('select408TeacherAction'), '考试结果页缺少自定义动作选择处理')
assert(typeof helper.submitFeedback === 'function', '408 AI helper 必须复用现有 feedback 能力')

console.log('408 AI teacher regression passed')

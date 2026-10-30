#!/usr/bin/env node
/* 408 专项 AI 老师静态回归：固定动作、固定版本、考试防泄题与三类复盘入口。 */
const fs = require('fs')
const path = require('path')
const assert = require('assert')

const miniRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(miniRoot, '..')
const backendRoot = path.join(repoRoot, 'backend')
const helper = require(path.join(miniRoot, 'subpackages/study/utils/ai-teacher-408.js'))

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
assert.deepStrictEqual(
  helper.PRIMARY_ACTIONS.map(item => item.action),
  ['explain_options', 'core_concept', 'similar_question', 'connect_knowledge'],
  '错题详情首屏只应展示四个互补动作'
)
assert.deepStrictEqual(
  new Set([...helper.PRIMARY_ACTIONS, ...helper.MORE_ACTIONS].map(item => item.action)),
  new Set(expectedActions),
  '主操作与更多操作必须完整覆盖七个兼容动作'
)

const schema = fs.readFileSync(path.join(backendRoot, 'app/schemas/ai_teacher_408.py'), 'utf8')
const prompt = fs.readFileSync(path.join(backendRoot, 'app/ai/prompts_408_teacher.py'), 'utf8')
const service = fs.readFileSync(path.join(backendRoot, 'app/services/ai_teacher_408_service.py'), 'utf8')
const aiRoute = fs.readFileSync(path.join(backendRoot, 'app/api/v1/ai.py'), 'utf8')

assert(!/\bprompt\s*:/.test(schema), '客户端请求 schema 不得暴露自由 prompt 字段')
expectedActions.forEach(action => assert(prompt.includes(`"${action}"`), `服务端缺少固定动作 ${action}`))
assert(prompt.includes('408-teacher-v3'), '专项讲解输出边界变更后必须升级 prompt version')
assert(prompt.includes('不得重新输出通用的'), '专项讲解 prompt 必须禁止重复完整错题复盘')
assert(service.includes('QuestionVersion'), '408 AI 必须从题目历史版本加载事实')
assert(service.includes('question_version_id'), '408 AI 必须携带固定 question_version_id')
assert(service.includes('UserKnowledgeState'), '408 AI 必须接入用户 mastery/confidence')
assert(service.includes('WrongQuestionErrorDiagnosis'), '408 AI 必须接入近期错因')
assert(service.includes('KnowledgeEdge'), '408 AI 必须接入知识图谱邻居')
assert(service.includes('check_token_limit'), '408 AI 必须复用 token budget')
assert(service.includes('record_token_usage'), '408 AI 必须记录 AI usage')
assert(service.includes('owned_practice_record_id'), '历史 question_version_id 必须校验属于当前用户练习事实')
assert(service.includes('if action == "connect_knowledge"'), '降级态只允许知识串联动作输出知识点列表')
assert(service.includes('"sections": []'), '专项讲解降级态不得回填完整三段式复盘')
assert(service.indexOf('await record_token_usage(') < service.indexOf('parsed = _parse_json_object(result.get("content"))'), 'provider 成功后应先记 usage，再解析结构化输出')
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
    apiSource: 'subpackages/study/wrong-detail/utils/wrong-detail-teacher-page-adapter.js',
    contextSource: 'subpackages/study/wrong-detail/utils/teacher-action-controller.js',
  },
  {
    js: 'subpackages/study/practice-result/index.js',
    wxml: 'subpackages/study/practice-result/index.wxml',
    handler: 'open408TeacherFromReview',
    extra: 'question_version_id',
    apiSource: 'subpackages/study/practice-result/utils/practice-result-teacher-page-adapter.js',
    contextSource: 'subpackages/study/practice-result/utils/review-408-teacher-controller.js',
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
  const apiSource = surface.apiSource
    ? fs.readFileSync(path.join(miniRoot, surface.apiSource), 'utf8') : js
  const contextSource = surface.contextSource
    ? fs.readFileSync(path.join(miniRoot, surface.contextSource), 'utf8') : js
  assert(apiSource.includes("api.post('/ai/408-teacher'"), `${surface.js} 未调用 408 teacher API`)
  assert(contextSource.includes(surface.extra), `${surface.js} 未携带 ${surface.extra} 上下文`)
  assert(js.includes(`${surface.handler}(`), `${surface.js} 缺少 ${surface.handler}`)
  assert(wxml.includes(surface.handler), `${surface.wxml} 未绑定 ${surface.handler}`)
  assert(js.includes('feedback408Teacher('), `${surface.js} 缺少 AI 反馈处理`)
  assert(wxml.includes('feedback408Teacher'), `${surface.wxml} 未提供 AI 反馈入口`)
})

const wrongDetailJs = fs.readFileSync(path.join(miniRoot, 'subpackages/study/wrong-detail/wrong-detail.js'), 'utf8')
const wrongDetailWxml = fs.readFileSync(path.join(miniRoot, 'subpackages/study/wrong-detail/wrong-detail.wxml'), 'utf8')
const wrongDetailWxss = fs.readFileSync(path.join(miniRoot, 'subpackages/study/wrong-detail/wrong-detail.wxss'), 'utf8')
assert(wrongDetailWxml.includes('AI 复盘'), '错题详情必须将 AI 能力统一为 AI 复盘入口')
assert(wrongDetailWxml.includes('teacherPrimaryActions'), 'AI 复盘必须展示精简后的首屏专项动作')
assert(wrongDetailWxml.includes('teacherMoreActions'), 'AI 复盘必须保留完整动作的更多入口')
assert(!wrongDetailWxml.includes('class="teacher-card"'), '错题详情不得继续渲染重复的独立 AI 老师卡片')
for (const handler of ['onAiSwipeStart', 'onAiSwipeEnd', 'onAiSwipeCancel']) {
  assert(wrongDetailJs.includes(`${handler}(`), `复盘卡片缺少 ${handler} 处理`)
  assert(wrongDetailWxml.includes(`="${handler}"`), `复盘卡片未绑定 ${handler}`)
}
assert(wrongDetailJs.includes('teacherLastAction'), '专项讲解失败后必须保留可重试动作')
assert(wrongDetailWxml.includes('class="diagnosis-summary"'), '我的错因必须使用轻量摘要布局')
assert(!wrongDetailWxml.includes('error-cause-paper.png'), '我的错因不应继续使用抢占空间的大幅插图')
assert(wrongDetailWxml.includes('class="ai-brand-icon"'), 'AI 复盘必须具备独立但克制的视觉标识')
assert(wrongDetailJs.includes('teacherActionsExpanded: false'), '更多专项动作默认必须收起')
assert(wrongDetailWxml.includes("teacherActionsExpanded ? 'is-expanded' : 'is-collapsed'"), '更多专项动作必须按当前状态显示')
assert(wrongDetailWxss.includes('.ai-deep-actions'), '专项追问必须保留动作布局样式')
assert(!/min-height:\s*(?:620|650|660|686|704|820|860)rpx/.test(wrongDetailWxss), '我的错因不得残留历史大卡片固定高度')
assert(!/\/\*\s*v(?:8|9|10|11|22|23)\b/.test(wrongDetailWxss), '错因样式不得继续依赖多版本级联覆盖')

const examWxml = fs.readFileSync(path.join(miniRoot, 'subpackages/exam/result/index.wxml'), 'utf8')
assert(examWxml.includes('交卷后专项 AI 老师'), '考试 AI 入口必须明确位于交卷后结果页')

const practiceJs = fs.readFileSync(path.join(miniRoot, 'subpackages/study/practice-result/index.js'), 'utf8')
const practiceWxml = fs.readFileSync(path.join(miniRoot, 'subpackages/study/practice-result/index.wxml'), 'utf8')
const examJs = fs.readFileSync(path.join(miniRoot, 'subpackages/exam/result/index.js'), 'utf8')
assert(practiceJs.includes('teacherActions: aiTeacher408.ACTIONS'), '普通练习结果页必须使用自定义 7 动作面板')
assert(examJs.includes('teacherActions: aiTeacher408.ACTIONS'), '考试结果页必须使用自定义 7 动作面板')
assert(practiceWxml.includes('select408TeacherAction'), '普通练习结果页缺少自定义动作选择处理')
assert(examWxml.includes('select408TeacherAction'), '考试结果页缺少自定义动作选择处理')
assert(typeof helper.submitFeedback === 'function', '408 AI helper 必须复用现有 feedback 能力')

const structuredFallback = helper.normalizeResult({
  action: 'explain_correct',
  summary: JSON.stringify({
    mistake_diagnosis: '先辨析核心概念。',
    knowledge_patch: '补齐相关规则。',
    review_task: '再做两道同类题。',
  }),
  sections: [],
  knowledge_points: [],
})
assert(structuredFallback, '结构化题库解析应可被前端规范化')
assert(!structuredFallback.summary.includes('{'), '专项 AI UI 不得回显 JSON 源码')
assert(structuredFallback.sections.some(item => item.heading === '错因诊断'), '结构化题库解析应渲染为人类可读分区')

console.log('408 AI teacher regression passed')

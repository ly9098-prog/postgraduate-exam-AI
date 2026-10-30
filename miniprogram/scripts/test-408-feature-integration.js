const assert = require('assert')
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const read = rel => fs.readFileSync(path.join(root, rel), 'utf8')
const has = (rel, patterns) => {
  const text = read(rel)
  patterns.forEach(pattern => assert.ok(pattern.test(text), `${rel} missing ${pattern}`))
}

// Regression: no runtime page may depend on the four v1 newly-added utility modules.
const forbidden = ['study-strategy', 'error-action-router', 'pomodoro-task-types', 'chapter-graduation']
for (const base of ['pages', 'subpackages']) {
  const stack = [path.join(root, base)]
  while (stack.length) {
    const current = stack.pop()
    fs.readdirSync(current, { withFileTypes: true }).forEach(entry => {
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) stack.push(full)
      else if (entry.name.endsWith('.js')) {
        const text = fs.readFileSync(full, 'utf8')
        forbidden.forEach(name => assert.ok(!text.includes(`utils/${name}`), `${full} still imports ${name}`))
      }
    })
  }
}


// Every static relative require used by runtime code must resolve to a real file.
for (const base of ['pages', 'subpackages', 'utils']) {
  const stack = [path.join(root, base)]
  while (stack.length) {
    const current = stack.pop()
    fs.readdirSync(current, { withFileTypes: true }).forEach(entry => {
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) stack.push(full)
      else if (entry.name.endsWith('.js')) {
        const text = fs.readFileSync(full, 'utf8')
        const requireRe = /require\((['"])([^'"]+)\1\)/g
        let match
        while ((match = requireRe.exec(text))) {
          const request = match[2]
          if (!request.startsWith('.')) continue
          const basePath = path.resolve(path.dirname(full), request)
          const candidates = [basePath, `${basePath}.js`, `${basePath}.json`, path.join(basePath, 'index.js')]
          assert.ok(candidates.some(candidate => fs.existsSync(candidate)), `${full} unresolved require ${request}`)
        }
      }
    })
  }
}

// P0: subject stage + manual weight, stored independently from backend plan payload.
has('subpackages/study/study-plan/index.wxml', [/四科阶段与权重/, /onStrategyStageChange/, /bindchanging="onStrategyWeightChange"/])
has('subpackages/study/study-plan/index.js', [/studyStrategy\.saveProfile/, /strategyWeightValid/, /stageOptions/])
has('utils/study-strategy.js', [/const studyStrategy =/, /buildNextBestAction/, /buildChoiceLossBudget/])
has('utils/storage.js', [/require\('\.\/study-strategy'\)/, /^\s+studyStrategy,$/m])

// P0: diagnosis -> next action automatic router, colocated with taxonomy.
has('subpackages/study/utils/error-diagnosis.js', [/buildNextAction/, /routeParamsForPractice/, /subject_code/])
has('subpackages/study/wrong-detail/wrong-detail.js', [/openNextErrorAction/])
has('subpackages/study/wrong-detail/utils/wrong-detail-diagnosis-flow.js', [/openNextErrorAction/, /errorDiagnosis\.buildNextAction/])
has('subpackages/study/wrong-detail/wrong-detail.wxml', [/NEXT ACTION/, /openNextErrorAction/])
const wrongCss = read('subpackages/study/wrong-detail/wrong-detail.wxss')
assert.strictEqual((wrongCss.match(/\.diagnosis-next-action\{/g) || []).length, 1, 'duplicate NEXT ACTION style block')

// P0: 130 choice-only loss budget is calculated and committed to dashboard state.
has('pages/dashboard/dashboard.js', [/buildChoiceLossBudget/, /choiceLossBudget,/])
has('pages/dashboard/dashboard.wxml', [/选择题失分预算/, /CHOICE ONLY/, /maxWrongQuestions/])

// P1: Pomodoro task types survive sessions and appear in stats.
has('pages/pomodoro/pomodoro.js', [/pomodoroTaskTypes/, /selectTaskType/, /selectedTaskTypeLabel/])
has('pages/pomodoro/utils/start-session-controller.js', [/pomodoroTaskTypes\.recordSession/])
const restoreControllers = [
  read('pages/pomodoro/utils/free-session-restore-controller.js'),
  read('pages/pomodoro/utils/countdown-session-restore-controller.js'),
]
restoreControllers.forEach(text => {
  assert.ok(/taskType: (sessionTaskType|taskType) \|\| ''/.test(text), 'legacy sessions must stay unclassified')
  assert.ok(/'未分类'/.test(text), 'legacy sessions must keep the unclassified label')
})
;[
  ...restoreControllers,
  read('pages/pomodoro/pomodoro.js'),
  read('pages/pomodoro/utils/start-session-controller.js'),
].forEach(text => {
  assert.ok(!/TaskType \|\| (options\.)?pomodoroTaskTypes\.DEFAULT_TYPE/.test(text), 'legacy sessions must not inherit default task type')
})
has('pages/pomodoro/pomodoro.wxml', [/任务类型/, /selectedTaskType/])
has('subpackages/productivity/pomodoro-stats/stats-load-view-flow.js', [/labelForSession/])
has('utils/pomodoro-task-types.js', [/const pomodoroTaskTypes =/, /typeForSession/])
has('utils/storage.js', [/require\('\.\/pomodoro-task-types'\)/, /^\s+pomodoroTaskTypes,$/m])

// P1: chapter graduation is computed next to tree grouping and shown on the map.
has('subpackages/knowledge/knowledge-subject/tree-groups.js', [/evaluateChapter/, /summarizeGroups/, /value == null/])
has('subpackages/knowledge/knowledge-subject/index.js', [/summarizeGroups/, /graduationLabel/])
has('subpackages/knowledge/knowledge-subject/index.wxml', [/章节毕业/, /graduationLabel/])

// P1: Study Hub is a true Next Best Action and can target no-data subjects by canonical code.
has('pages/home/home.js', [/buildNextBestAction/, /route === 'pomodoro'/])
has('pages/home/home.wxml', [/primaryTaskTitle/, /primaryTaskAction/, /primaryTaskKicker/, /今日刷题进度/])
has('subpackages/study/practice/utils/practice-launch-flow.js', [/subjectCode/, /preset\.subjectCode/])
has('pages/pomodoro/pomodoro.js', [/fromSubjectCode/, /opts && opts\.subject_code/])

// Compatibility invariant: local strategy fields must not be added to legacy study-plan API payload.
const plan = read('subpackages/study/study-plan/index.js')
const payloadMatch = plan.match(/(?:const|var|let) payload = \{([\s\S]*?)\n\s*\}/)
assert.ok(payloadMatch, 'study-plan payload not found')
assert.ok(!/subjects|strategy|weight|stage/.test(payloadMatch[1]), 'legacy /study-plan payload was extended unexpectedly')

console.log('408 feature integration checks passed')

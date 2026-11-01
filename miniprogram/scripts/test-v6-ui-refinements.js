/**
 * v6 targeted regression checks for dashboard/study-plan/pomodoro refinements.
 * Static checks only: no WeChat runtime or backend required.
 */
/* eslint-disable no-console */
const assert = require('assert')
const fs = require('fs')
const path = require('path')

function source(rel) {
  return fs.readFileSync(path.resolve(__dirname, '..', rel), 'utf8')
}

// 1) Dashboard: both hero views remain mounted in one stable grid deck.
const dashboardWxml = source('pages/dashboard/dashboard.wxml')
const dashboardWxss = source('pages/dashboard/dashboard.wxss')
const dashboardJs = source('pages/dashboard/dashboard.js')
assert.ok(dashboardWxml.includes('class="hero-card-deck"'))
assert.ok(dashboardWxml.includes("heroCardMode === 'summary' ? 'is-active'"))
assert.ok(dashboardWxml.includes("heroCardMode === 'budget' ? 'is-active'"))
assert.ok(!dashboardWxml.includes('hero-card-swap-'))
assert.ok(dashboardWxss.includes('.hero-card-deck'))
assert.ok(dashboardWxss.includes('grid-row: 1;'))
assert.ok(dashboardWxss.includes('.hero-card-panel.is-active'))
assert.ok(!dashboardWxss.includes('.hero-card-swap-out'))
assert.ok(/toggleHeroCard\(\)\s*\{[\s\S]*const nextMode[\s\S]*this\.setData\(\{ heroCardMode: nextMode \}\)[\s\S]*\}/.test(dashboardJs))
assert.ok(!dashboardJs.includes('_heroCardSwapTimer'))

// 2) Study plan: daily question target is restored and shares the home storage key.
const planWxml = source('subpackages/study/study-plan/index.wxml')
const planJs = source('subpackages/study/study-plan/index.js')
const homeGrowthController = source('pages/home/utils/growth-page-controller.js')
assert.ok(planWxml.includes('每日目标题数'))
assert.ok(planWxml.includes('{{questionGoalOptions[questionGoalIndex]}} 题'))
assert.ok(planWxml.includes('bindchange="onQuestionGoalChange"'))
assert.ok(planWxml.includes('<text class="plan-hero-step-total">06</text>'))
assert.ok(planJs.includes("const QUESTION_GOAL_OPTIONS = [10, 20, 30, 50]"))
assert.ok(planJs.includes("const QUESTION_GOAL_KEY = 'home_today_goal_total'"))
assert.ok(homeGrowthController.includes("const TODAY_GOAL_KEY = 'home_today_goal_total'"))
assert.ok(planJs.includes('storage.set(QUESTION_GOAL_KEY, value)'))
assert.ok(planJs.includes('this._syncQuestionGoalFromStorage()'))

// 3-6) Pomodoro: divider-heading direction, centered task types, denser/larger subject circles,
// and an explicit dark palette for the subject launcher module.
const pomodoroWxml = source('pages/pomodoro/pomodoro.wxml')
const pomodoroWxss = source('pages/pomodoro/pomodoro.wxss')
const headingCount = (pomodoroWxml.match(/class="control-section-title"/g) || []).length
assert.strictEqual(headingCount, 3)
assert.ok(pomodoroWxml.includes('<text class="control-section-text">选择科目</text>'))
assert.ok(pomodoroWxml.includes('<text class="control-section-text">任务类型</text>'))
assert.ok(pomodoroWxml.includes('<text class="control-section-text">时长</text>'))
assert.ok(!pomodoroWxml.includes('——任务类型——'))
assert.ok(!pomodoroWxml.includes('——时长——'))
assert.ok(!pomodoroWxml.includes('<scroll-view class="task-type-scroll"'), 'task types should not depend on horizontal scroll centering')
assert.ok(/\.task-type-row\s*\{[\s\S]*justify-content:\s*center;/.test(pomodoroWxss))
assert.ok(/\.subj-icon-wrap\s*\{[\s\S]*width:\s*104rpx;[\s\S]*height:\s*104rpx;/.test(pomodoroWxss))
assert.ok(/\.subj-grid\s*\{[\s\S]*row-gap:\s*6rpx;/.test(pomodoroWxss))
assert.ok(pomodoroWxss.includes('.theme-dark .subj-icon-wrap'))
assert.ok(pomodoroWxss.includes('.theme-dark .subj-card.active .subj-icon-wrap'))
assert.ok(pomodoroWxss.includes('.theme-dark .subj-card.active .subj-name'))

console.log('v6 targeted UI regression checks passed')

/**
 * Subject loading and pure apply planning for the Pomodoro page.
 *
 * The loader fetches the current catalog and calls injected page callbacks
 * for state updates; buildApplySubjectsPlan remains a pure patch planner.
 */
const { normalizeCachedSubjects } = require('./subject-options')
const { findRouteSubject, findLegacySubject } = require('./subject-selection')

function createSubjectLoadController(options) {
  return {
    load: () => loadSubjects(options),
  }
}

async function loadSubjects(options) {
  options.setSubjectsState({ subjectsLoading: true, subjectsError: '' })
  try {
    const rawTree = await options.fetchSubjects()
    const tree = options.filterSubjectTree(rawTree)
    if (!tree || !Array.isArray(tree)) {
      throw new Error('科目数据格式错误')
    }
    const choices = options.buildSubjectChoices(tree).choices
    options.applySubjects(choices)
  } catch (error) {
    options.logError('加载科目失败', error)
    options.applySubjects([], { migrateRunningState: false })
    options.setSubjectsState({
      subjectsLoading: false,
      subjectsError: '科目加载失败，请稍后重试',
    })
  }
}

function buildApplySubjectsPlan(flat, pageData) {
  const { choices, aggregate, leaves, coreSubjects } = normalizeCachedSubjects(flat)
  const patches = [{
    subjects: choices,
    aggregateAvailable: !!aggregate && coreSubjects.length === 4,
    coreSubjects,
    subjectsLoading: false,
    subjectsError: '',
  }]

  const route = {
    subjectId: pageData.fromSubjectId,
    subjectCode: pageData.fromSubjectCode,
  }
  const routeSelection = (route.subjectId || route.subjectCode)
    ? findRouteSubject({ route, aggregate, leaves, coreSubjects })
    : null
  if (routeSelection) {
    patches.push(routeSelection)
  }

  const legacySelection = findLegacySubject(pageData.selectedSubject, leaves)
  if (legacySelection) {
    patches.push(legacySelection)
  }

  const selected = choices.find(subject => Number(subject.id) === Number(pageData.selectedSubjectId))
  const selectionUnavailable = pageData.selectedSubjectId && (!selected || selected._disabled)
  if (pageData.phase === 'idle' && selectionUnavailable && !routeSelection && !legacySelection) {
    patches.push({ selectedSubjectId: null, selectedSubject: null, allocationMode: 'single' })
  }

  return { patches, leaves }
}

module.exports = { buildApplySubjectsPlan, createSubjectLoadController }

const {
  STUDY_STRATEGY_STORAGE_KEY,
  SCHEMA_VERSION,
  CHOICE_TOTAL_POINTS,
  CHOICE_LOSS_BUDGET_POINTS,
  CHOICE_TARGET_POINTS,
  SUBJECTS,
  STAGES,
  STAGE_MAP,
  stageLabel,
  subjectCodeFromItem,
} = require('./study-strategy-meta')
const {
  createDefaultProfile,
  normalizeProfile,
  getProfile,
  saveProfile,
  validateProfile,
  getSubjectStrategy,
} = require('./study-strategy-profile')
const { buildChoiceLossBudget, buildNextBestAction } = require('./study-strategy-plan')

// eslint-disable-next-line no-use-before-define
const studyStrategy = {
  STORAGE_KEY: STUDY_STRATEGY_STORAGE_KEY,
  SCHEMA_VERSION,
  SUBJECTS,
  STAGES,
  STAGE_MAP,
  CHOICE_TOTAL_POINTS,
  CHOICE_LOSS_BUDGET_POINTS,
  CHOICE_TARGET_POINTS,
  createDefaultProfile,
  normalizeProfile,
  getProfile,
  saveProfile,
  validateProfile,
  getSubjectStrategy,
  stageLabel,
  subjectCodeFromItem,
  buildChoiceLossBudget,
  buildNextBestAction,
}

module.exports = { studyStrategy }

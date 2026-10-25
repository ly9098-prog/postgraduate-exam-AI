const { getSubjectName } = require('./subject-meta')

const SUBJECT_COLOR = '#3B82F6'

function createSubjectViewController(options) {
  return {
    label: key => label(options, key),
    color: () => SUBJECT_COLOR,
  }
}

function label(options, key) {
  const subject = options.getSubjects().find(item => item.code === key)
  return subject ? subject.name : getSubjectName(key)
}

module.exports = { createSubjectViewController, SUBJECT_COLOR }

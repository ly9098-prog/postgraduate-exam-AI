function createPracticeSubjectLoadController(options) {
  return {
    load: requestOptions => loadSubjects(requestOptions, options),
  }
}

async function loadSubjects(requestOptions, options) {
  const requestSeq = options.nextRequestSeq()
  try {
    const response = await options.fetchSubjects()
    if (!options.isCurrent(requestSeq)) return
    await commitSubjectTree(response, requestOptions, options)
  } catch (error) {
    if (!options.isCurrent(requestSeq)) return
    options.logError('加载科目树失败', error)
    if (!requestOptions.silent) options.showToast({ title: '加载科目失败', icon: 'none' })
  }
}

async function commitSubjectTree(response, requestOptions, options) {
  const subjectTree = options.normalizeSubjectTree(options.filterSubjectTree(response || []))
  options.setData({ subjectTree })
  if (requestOptions.preserveSelection && options.getSelectedSubjectId()) {
    options.preserveSelectedSubject(subjectTree)
  } else {
    options.initDefaultSubject(subjectTree)
  }
  if (requestOptions.skipAutostart) return
  const presetApplied = await options.applyLaunchPreset(subjectTree)
  if (presetApplied && options.shouldAutostart()) await options.startPractice()
}

module.exports = {
  createPracticeSubjectLoadController,
}

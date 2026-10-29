function processWqData(wq, safeMode, { isTrueFalseType, config, buildRenderModel, adapter, _subjectLabel, _errorTypeLabel }) {
const questionType = wq.question_type || wq.type || ''
let opts = wq.options || null
if ((!opts || Object.keys(opts).length === 0) && isTrueFalseType(questionType)) {
opts = { A: '正确', B: '错误' }
}
const optionKeys = opts ? Object.keys(opts) : []
var renderCfg = { enableMathImage: false, DEV: config.DEV }
if (safeMode) renderCfg.SAFE_MODE = true
const _renderModel = buildRenderModel(wq, opts, renderCfg)
const _optionList = adapter.buildOptionListReadonly(wq, opts, optionKeys, wq.answer, wq.wrong_answer)
const blankOptionGroups = adapter.enrichBlankOptionGroupsReadonly(
adapter.getBlankOptionGroups(wq), wq.answer, wq.wrong_answer
)
return {
wq,
_optionList,
_optionKeys: optionKeys,
_opts: opts,
_blankOptionGroups: blankOptionGroups,
_hasBlankOptionGroups: blankOptionGroups.length > 0,
_renderModel,
subjectLabelText: wq.subject_name || _subjectLabel(wq.subject_code),
errorTypeLabelText: _errorTypeLabel(wq.error_type),
}
}

module.exports = { processWqData }

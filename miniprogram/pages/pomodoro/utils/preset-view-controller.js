function createPresetViewController(options) {
  return {
    label: key => label(options, key),
  }
}

function label(options, key) {
  const preset = options.getPresets().find(item => item.key === key)
  return preset ? preset.label : key
}

module.exports = { createPresetViewController }

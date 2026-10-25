const LEVELS = ['medium', 'large']

function createFontSizeController(options) {
  return {
    cycle: () => cycle(options),
  }
}

function cycle(options) {
  const current = options.getCurrentLevel()
  const index = LEVELS.indexOf(current)
  const next = LEVELS[(index + 1) % LEVELS.length]
  options.setLevel(next)
  options.persist(next)
}

module.exports = { createFontSizeController, FONT_SIZE_LEVELS: LEVELS }

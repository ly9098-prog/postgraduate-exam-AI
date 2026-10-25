const TYPES = ['excellent', 'award', 'thumbsUp']

function createCelebrationTypeController(options) {
  return {
    next: () => next(options),
  }
}

function next(options) {
  const index = options.getIndex() || 0
  const nextIndex = (index + 1) % TYPES.length
  options.setIndex(nextIndex)
  return TYPES[index]
}

module.exports = { createCelebrationTypeController, CELEBRATION_TYPES: TYPES }

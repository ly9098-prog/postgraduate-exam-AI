const store = require('../../../../utils/launch-session-store')

function createReviewStateWriter(page) {
  const owner = store.userId()
  return (patch, callback) => {
    if (owner && owner === store.userId()) {
      if (patch.phase === 'reviewing') {
        store.markReview((page._reviewSession || {}).taskDate)
      } else if (['group-result', 'empty'].includes(patch.phase)) {
        store.clearActive('review-today')
      }
    }
    page.setData(patch, callback)
  }
}

function createReviewActivityClearer() {
  const owner = store.userId()
  return () => {
    if (owner && owner === store.userId()) store.clearActive('review-today')
  }
}

module.exports = { createReviewStateWriter, createReviewActivityClearer }

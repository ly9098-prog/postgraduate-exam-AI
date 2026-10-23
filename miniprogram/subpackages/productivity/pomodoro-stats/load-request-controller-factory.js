const {
  buildLoadRequestControllerCapabilities,
} = require('./load-request-controller-capabilities')

function createLoadRequestControllerFactory(options) {
  return {
    create() {
      return options.createLoadRequestController(
        buildLoadRequestControllerCapabilities(options)
      )
    },
  }
}

module.exports = {
  createLoadRequestControllerFactory,
}

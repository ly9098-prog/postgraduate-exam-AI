function createSubjectMetaController(options) {
  return {
    ensure() {
      if (options.isLoaded()) return Promise.resolve(options.getMeta())
      if (options.getPromise()) return options.getPromise()
      const promise = this.load()
      options.setPromise(promise)
      return promise
    },
    async load() {
      try {
        const rawTree = await options.getSubjectTree()
        options.setMeta(options.buildSubjectMeta(rawTree))
        return options.getMeta()
      } catch (error) {
        options.logError('加载科目树失败', error)
        options.setMeta(null)
        return null
      } finally {
        options.markLoaded()
        options.setPromise(null)
      }
    },
  }
}

module.exports = {
  createSubjectMetaController,
}

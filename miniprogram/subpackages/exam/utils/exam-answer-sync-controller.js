function createExamAnswerSyncController(options) {
  const syncing = Object.create(null)
  return {
    syncItem: itemId => syncItemImpl(options, syncing, itemId),
    flushAllPending: flushOptions => flushAllPendingImpl(options, syncing, flushOptions),
  }
}

async function syncItemImpl(options, syncing, itemId) {
  itemId = String(itemId)
  if (syncing[itemId]) return syncing[itemId]

  const run = async () => {
    let pass = 0
    while (options.getPendingItem(itemId)) {
      const snapshot = Object.assign({}, options.getPendingItem(itemId))
      try {
        const response = await options.patchAnswer(itemId, snapshot)
        if (response && response.status && response.status !== 'in_progress') {
          options.removePendingItem(itemId)
          options.persistPending()
          options.onTerminalSync()
          return
        }
        pass += 1
        if (options.isPendingItemUnchanged(itemId, snapshot)) {
          options.removePendingItem(itemId)
          options.persistPending()
        }
        // A changed snapshot stays queued for the next pass, but a page that
        // keeps mutating during every PATCH must not create an infinite loop.
        if (pass >= options.getMaxSyncPasses()) return
      } catch (error) {
        if (await options.resolveTerminalSyncConflict(error)) return
        throw error
      }
    }
  }

  syncing[itemId] = run().finally(() => { delete syncing[itemId] })
  return syncing[itemId]
}

async function flushAllPendingImpl(options, syncing, flushOptions = {}) {
  try {
    // Re-scan after each pass. An item can be queued while an earlier item is
    // awaiting its PATCH; submission freezes editing, so the loop converges.
    while (true) {
      const ids = options.getPendingItemIds()
      if (!ids.length) return true
      for (let idIndex = 0; idIndex < ids.length; idIndex += 1) {
        await syncItemImpl(options, syncing, ids[idIndex])
      }
    }
  } catch (error) {
    if (!flushOptions.quiet) options.showFlushError()
    throw error
  }
}

module.exports = {
  createExamAnswerSyncController,
}

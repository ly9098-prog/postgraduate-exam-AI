// Resolve helpers on access so replacements stay live; binding preserves callbacks.
function buildItemViewCapabilities(page) {
return {
get positiveNumber() { return page._positiveNumber.bind(page) },
get resolveReviewCount() { return page._resolveReviewCount.bind(page) },
get masteryProgress() { return page._masteryProgress.bind(page) },
get reviewDueInfo() { return page._reviewDueInfo.bind(page) },
get isRecentDate() { return page._isRecentDate.bind(page) },
get resolveItemStatus() { return page._resolveItemStatus.bind(page) },
get resolveItemContent() { return page._resolveItemContent.bind(page) },
get buildDecoratedItem() { return page._buildDecoratedItem.bind(page) },
get shortDateLabel() { return page._shortDateLabel.bind(page) },
get toCleanText() { return page._toCleanText.bind(page) },
get subjectLabel() { return page._subjectLabel.bind(page) },
get errorTypeLabel() { return page._errorTypeLabel.bind(page) },
get timeLabel() { return page._timeLabel.bind(page) }
}
}

function buildAnalysisViewCapabilities(page) {
return {
get rowsFromStats() { return page._rowsFromStats.bind(page) },
get countsFromList() { return page._countsFromList.bind(page) },
get topItems() { return page._topItems.bind(page) },
get errorTypeLabel() { return page._errorTypeLabel.bind(page) },
get toPercentItems() { return page._toPercentItems.bind(page) },
get subjectLabel() { return page._subjectLabel.bind(page) },
get buildSummaryCards() { return page._buildSummaryCards.bind(page) },
get buildActionPlan() { return page._buildActionPlan.bind(page) },
get radarPolygonStyle() { return page._radarPolygonStyle.bind(page) },
get radarAxisText() { return page._radarAxisText.bind(page) },
get focusInsight() { return page._focusInsight.bind(page) },
get positiveNumber() { return page._positiveNumber.bind(page) }
}
}

module.exports = { buildItemViewCapabilities, buildAnalysisViewCapabilities }

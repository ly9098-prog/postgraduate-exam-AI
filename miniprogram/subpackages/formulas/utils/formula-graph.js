/**
 * formula-graph.js — Unified graph image URL resolution for formula cards.
 *
 * The backend returns graph asset data in the `graph_asset` field:
 *   { graph_asset: { image_url, thumbnail_url, ... } }
 *
 * These helpers extract the URL and normalise it into the flat
 * `graphImageUrl` / `graphThumbnailUrl` properties consumed by
 * the formula-card component.
 */

function resolveGraphImageUrl(card) {
  return (
    card?.graph_asset?.image_url ||
    card?.graph_asset?.imageUrl ||
    card?.graphAsset?.image_url ||
    card?.graphAsset?.imageUrl ||
    card?.graph_image_url ||
    card?.graphImageUrl ||
    ''
  )
}

function resolveGraphThumbnailUrl(card) {
  return (
    card?.graph_asset?.thumbnail_url ||
    card?.graph_asset?.thumbnailUrl ||
    card?.graphAsset?.thumbnail_url ||
    card?.graphAsset?.thumbnailUrl ||
    card?.graph_thumbnail_url ||
    card?.graphThumbnailUrl ||
    card?.graph_asset?.image_url ||
    card?.graph_asset?.imageUrl ||
    resolveGraphImageUrl(card)
  )
}

module.exports = {
  resolveGraphImageUrl,
  resolveGraphThumbnailUrl,
}

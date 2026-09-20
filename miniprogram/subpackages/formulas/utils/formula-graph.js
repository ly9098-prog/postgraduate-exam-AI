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

const config = require('../../../config')

function apiOrigin() {
  var base = String((config && config.BASE_URL) || '').trim()
  var match = base.match(/^(https?:\/\/[^/]+)/i)
  return match ? match[1].replace(/\/$/, '') : ''
}

function normalizeGraphAssetUrl(value) {
  var raw = String(value || '').trim()
  if (!raw) return ''

  var origin = apiOrigin()
  if (raw.indexOf('//') === 0) raw = 'https:' + raw

  // Backend local-static assets may be returned as root-relative paths.
  if (raw.charAt(0) === '/') {
    return origin ? origin + raw : raw
  }
  if (raw.indexOf('static/formulas/') === 0) {
    return origin ? origin + '/' + raw : '/' + raw
  }

  var absolute = raw.match(/^(https?):\/\/([^/]+)(\/.*)?$/i)
  if (!absolute) return raw

  var host = String(absolute[2] || '').toLowerCase()
  var path = String(absolute[3] || '')
  var marker = '/static/formulas/'
  var markerIndex = path.indexOf(marker)
  if (markerIndex < 0) return raw

  var baseHostMatch = origin.match(/^https?:\/\/([^/]+)$/i)
  var baseHost = baseHostMatch ? String(baseHostMatch[1]).toLowerCase() : ''
  var isLocalHost = host === 'localhost' || host.indexOf('localhost:') === 0 ||
    host === '127.0.0.1' || host.indexOf('127.0.0.1:') === 0 ||
    host === '0.0.0.0' || host.indexOf('0.0.0.0:') === 0

  // Repair stale localhost URLs and PUBLIC_BASE_URL values that accidentally
  // included /api/v1 before /static/formulas/. Keep external CDN/COS URLs.
  if (origin && (isLocalHost || host === baseHost)) {
    return origin + path.slice(markerIndex)
  }
  return raw
}

function resolveGraphImageUrl(card) {
  return normalizeGraphAssetUrl(
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
  return normalizeGraphAssetUrl(
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
  normalizeGraphAssetUrl,
  resolveGraphImageUrl,
  resolveGraphThumbnailUrl,
}

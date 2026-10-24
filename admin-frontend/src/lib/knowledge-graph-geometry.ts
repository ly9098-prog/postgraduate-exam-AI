/**
 * Pure geometry helpers for knowledge graph edge routing,
 * extracted from knowledge-graph/page.tsx.
 */

interface Point {
  x: number;
  y: number;
}

/**
 * Evaluate a cubic Bézier curve at parameter t.
 */
export function cubicPoint(
  start: Point,
  control1: Point,
  control2: Point,
  end: Point,
  t: number,
): Point {
  const mt = 1 - t;
  return {
    x: mt * mt * mt * start.x + 3 * mt * mt * t * control1.x + 3 * mt * t * t * control2.x + t * t * t * end.x,
    y: mt * mt * mt * start.y + 3 * mt * mt * t * control1.y + 3 * mt * t * t * control2.y + t * t * t * end.y,
  };
}

/**
 * Compute the unit normal vector of a cubic Bézier curve at parameter t.
 */
export function cubicUnitNormal(
  start: Point,
  control1: Point,
  control2: Point,
  end: Point,
  t: number,
): Point {
  const mt = 1 - t;
  const dx = 3 * mt * mt * (control1.x - start.x)
    + 6 * mt * t * (control2.x - control1.x)
    + 3 * t * t * (end.x - control2.x);
  const dy = 3 * mt * mt * (control1.y - start.y)
    + 6 * mt * t * (control2.y - control1.y)
    + 3 * t * t * (end.y - control2.y);
  const length = Math.max(0.001, Math.hypot(dx, dy));
  return { x: -dy / length, y: dx / length };
}

/**
 * Test whether two line segments properly intersect (not just touch at endpoints).
 */
export function segmentsProperlyIntersect(
  a: Point,
  b: Point,
  c: Point,
  d: Point,
): boolean {
  const cross = (p: Point, q: Point, r: Point) =>
    (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  const abC = cross(a, b, c);
  const abD = cross(a, b, d);
  const cdA = cross(c, d, a);
  const cdB = cross(c, d, b);
  const epsilon = 0.01;
  return ((abC > epsilon && abD < -epsilon) || (abC < -epsilon && abD > epsilon))
    && ((cdA > epsilon && cdB < -epsilon) || (cdA < -epsilon && cdB > epsilon));
}

/**
 * Count the number of proper intersections between two polylines.
 */
export function polylineIntersectionCount(
  route: Point[],
  other: Point[],
): number {
  let count = 0;
  for (let i = 0; i < route.length - 1; i += 1) {
    for (let j = 0; j < other.length - 1; j += 1) {
      if (segmentsProperlyIntersect(route[i], route[i + 1], other[j], other[j + 1])) count += 1;
    }
  }
  return count;
}

import { describe, it, expect } from "vitest";
import {
  cubicPoint,
  cubicUnitNormal,
  segmentsProperlyIntersect,
  polylineIntersectionCount,
  getNodeLabelPlacement,
} from "./knowledge-graph-geometry";

describe("cubicPoint", () => {
  it("returns start at t=0", () => {
    const p = cubicPoint({x:0,y:0}, {x:1,y:1}, {x:2,y:2}, {x:3,y:3}, 0);
    expect(p).toEqual({ x: 0, y: 0 });
  });
  it("returns end at t=1", () => {
    const p = cubicPoint({x:0,y:0}, {x:1,y:1}, {x:2,y:2}, {x:3,y:3}, 1);
    expect(p).toEqual({ x: 3, y: 3 });
  });
  it("returns midpoint at t=0.5 for linear control points", () => {
    const p = cubicPoint({x:0,y:0}, {x:1,y:0}, {x:2,y:0}, {x:3,y:0}, 0.5);
    expect(p.x).toBeCloseTo(1.5);
    expect(p.y).toBeCloseTo(0);
  });
});

describe("cubicUnitNormal", () => {
  it("returns a unit vector", () => {
    const n = cubicUnitNormal({x:0,y:0}, {x:1,y:0}, {x:2,y:0}, {x:3,y:0}, 0.5);
    const len = Math.hypot(n.x, n.y);
    expect(len).toBeCloseTo(1, 2);
  });
  it("is perpendicular to tangent for horizontal line", () => {
    const n = cubicUnitNormal({x:0,y:0}, {x:1,y:0}, {x:2,y:0}, {x:3,y:0}, 0.5);
    expect(Math.abs(n.x)).toBeCloseTo(0, 2);
    expect(Math.abs(n.y)).toBeCloseTo(1, 2);
  });
});

describe("segmentsProperlyIntersect", () => {
  it("detects crossing segments", () => {
    expect(segmentsProperlyIntersect({x:0,y:0}, {x:4,y:4}, {x:0,y:4}, {x:4,y:0})).toBe(true);
  });
  it("returns false for parallel segments", () => {
    expect(segmentsProperlyIntersect({x:0,y:0}, {x:4,y:0}, {x:0,y:1}, {x:4,y:1})).toBe(false);
  });
  it("returns false for non-crossing segments", () => {
    expect(segmentsProperlyIntersect({x:0,y:0}, {x:1,y:1}, {x:5,y:5}, {x:6,y:6})).toBe(false);
  });
  it("returns false for touching endpoints", () => {
    expect(segmentsProperlyIntersect({x:0,y:0}, {x:1,y:0}, {x:1,y:0}, {x:2,y:0})).toBe(false);
  });
});

describe("polylineIntersectionCount", () => {
  it("counts crossings between two polylines", () => {
    const route = [{x:0,y:0}, {x:4,y:4}];
    const other = [{x:0,y:4}, {x:4,y:0}];
    expect(polylineIntersectionCount(route, other)).toBe(1);
  });
  it("returns 0 for non-crossing polylines", () => {
    const route = [{x:0,y:0}, {x:1,y:0}];
    const other = [{x:0,y:5}, {x:1,y:5}];
    expect(polylineIntersectionCount(route, other)).toBe(0);
  });
  it("returns 0 for empty polylines", () => {
    expect(polylineIntersectionCount([], [])).toBe(0);
  });
  it("returns 0 for single-point polylines", () => {
    expect(polylineIntersectionCount([{x:0,y:0}], [{x:1,y:1}])).toBe(0);
  });
});

describe("getNodeLabelPlacement", () => {
  it("places label below when no anchor", () => {
    const p = getNodeLabelPlacement({ id: 1, x: 0, y: 0, name: "A" }, null, 20, false, 60);
    expect(p.textAnchor).toBe("middle");
    expect(p.y).toBe(37);
  });
  it("places label below when anchor is self", () => {
    const node = { id: 1, x: 0, y: 0, name: "A" };
    const p = getNodeLabelPlacement(node, node, 20, false, 60);
    expect(p.textAnchor).toBe("middle");
  });
  it("places label right when node is to the right of anchor", () => {
    const p = getNodeLabelPlacement({ id: 2, x: 100, y: 0, name: "B" }, { id: 1, x: 0, y: 0 }, 20, false, 60);
    expect(p.textAnchor).toBe("start");
    expect(p.x).toBe(30);
  });
  it("places label left when node is to the left of anchor", () => {
    const p = getNodeLabelPlacement({ id: 2, x: -100, y: 0, name: "B" }, { id: 1, x: 0, y: 0 }, 20, false, 60);
    expect(p.textAnchor).toBe("end");
    expect(p.x).toBe(-30);
  });
  it("places label above when node is above anchor", () => {
    const p = getNodeLabelPlacement({ id: 2, x: 0, y: -100, name: "B" }, { id: 1, x: 0, y: 0 }, 20, false, 60);
    expect(p.textAnchor).toBe("middle");
    expect(p.y).toBe(-30);
  });
  it("places label below when node is below anchor", () => {
    const p = getNodeLabelPlacement({ id: 2, x: 0, y: 100, name: "B" }, { id: 1, x: 0, y: 0 }, 20, false, 60);
    expect(p.textAnchor).toBe("middle");
    expect(p.y).toBe(37);
  });
  it("includes meta line offset when withMeta is true", () => {
    const p = getNodeLabelPlacement({ id: 1, x: 0, y: 0, name: "A" }, null, 20, true, 60);
    expect(p.metaY).toBe(50);
  });
});

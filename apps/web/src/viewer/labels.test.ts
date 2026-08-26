// Deterministic label layout (ruling 8).
//
// The layout is a pure function so it can be tested without a browser and so it produces
// the same frame every time — Phase 3's replay stability (3.7) depends on that.
import { describe, expect, it } from "vitest";

import { type LabelCandidate, estimateLabelSize, layoutLabels } from "./labels";

const VIEWPORT = { width: 1280, height: 900 };

function candidate(over: Partial<LabelCandidate> = {}): LabelCandidate {
  return {
    id: "p",
    text: "Part",
    importance: "core",
    anchorX: 640,
    anchorY: 450,
    depth: 5,
    occluded: false,
    ...estimateLabelSize(over.text ?? "Part"),
    ...over,
  };
}

describe("label layout", () => {
  it("places a lone label next to its anchor", () => {
    const { placed, dropped } = layoutLabels([candidate()], VIEWPORT);
    expect(dropped).toEqual([]);
    expect(placed).toHaveLength(1);
    expect(placed[0]?.needsLeader).toBe(false);
  });

  it("displaces a colliding label rather than stacking it", () => {
    const a = candidate({ id: "a" });
    const b = candidate({ id: "b" });
    const { placed } = layoutLabels([a, b], VIEWPORT);
    expect(placed).toHaveLength(2);

    const [first, second] = placed;
    const collides =
      first!.x < second!.x + second!.width &&
      first!.x + first!.width > second!.x &&
      first!.y < second!.y + second!.height &&
      first!.y + first!.height > second!.y;
    expect(collides, "two labels occupy the same box").toBe(false);
  });

  it("gives a displaced label a leader line", () => {
    const crowd = Array.from({ length: 6 }, (_, i) => candidate({ id: `p${i}` }));
    const { placed } = layoutLabels(crowd, VIEWPORT);
    expect(placed.filter((p) => p.needsLeader).length).toBeGreaterThan(0);
  });

  it("drops an occluded part's label entirely", () => {
    const { placed, dropped, droppedOccluded } = layoutLabels(
      [candidate({ id: "hidden", occluded: true })],
      VIEWPORT,
    );
    expect(placed).toEqual([]);
    expect(dropped).toEqual(["hidden"]);
    expect(droppedOccluded).toBe(1);
  });

  it("drops secondary labels before core ones when space runs out", () => {
    // One narrow viewport, many labels on one anchor: far more than can fit.
    const tight = { width: 300, height: 220 };
    const parts = [
      ...Array.from({ length: 12 }, (_, i) =>
        candidate({ id: `core${i}`, importance: "core" as const, anchorX: 140, anchorY: 110 }),
      ),
      ...Array.from({ length: 12 }, (_, i) =>
        candidate({
          id: `sec${i}`,
          importance: "secondary" as const,
          anchorX: 140,
          anchorY: 110,
        }),
      ),
    ];
    const { placed, droppedByImportance, droppedForSpace } = layoutLabels(parts, tight);

    expect(droppedForSpace).toBeGreaterThan(0);
    // D-006 reserved `importance` with no behaviour; this is the first consumer.
    expect(droppedByImportance.secondary).toBeGreaterThan(droppedByImportance.core);
    expect(placed.filter((p) => p.id.startsWith("core")).length).toBeGreaterThanOrEqual(
      placed.filter((p) => p.id.startsWith("sec")).length,
    );
  });

  it("reports how many were dropped and why", () => {
    const layout = layoutLabels(
      [candidate({ id: "a" }), candidate({ id: "b", occluded: true })],
      VIEWPORT,
    );
    expect(layout.dropped.length).toBe(layout.droppedOccluded + layout.droppedForSpace);
  });

  it("never places a label outside the viewport", () => {
    const edge = [
      candidate({ id: "left", anchorX: 2, anchorY: 450 }),
      candidate({ id: "right", anchorX: 1278, anchorY: 450 }),
      candidate({ id: "top", anchorX: 640, anchorY: 2 }),
      candidate({ id: "bottom", anchorX: 640, anchorY: 898 }),
    ];
    for (const placement of layoutLabels(edge, VIEWPORT).placed) {
      expect(placement.x).toBeGreaterThanOrEqual(0);
      expect(placement.y).toBeGreaterThanOrEqual(0);
      expect(placement.x + placement.width).toBeLessThanOrEqual(VIEWPORT.width);
      expect(placement.y + placement.height).toBeLessThanOrEqual(VIEWPORT.height);
    }
  });

  it("is deterministic — the same input lays out identically", () => {
    const parts = Array.from({ length: 20 }, (_, i) =>
      candidate({ id: `p${i}`, anchorX: 300 + (i % 5) * 30, anchorY: 300 + Math.floor(i / 5) * 25 }),
    );
    expect(layoutLabels(parts, VIEWPORT)).toEqual(layoutLabels(parts, VIEWPORT));
  });

  it("orders by depth within an importance tier, so nearer labels win", () => {
    const far = candidate({ id: "far", depth: 50 });
    const near = candidate({ id: "near", depth: 1 });
    const { placed } = layoutLabels([far, near], VIEWPORT);
    expect(placed[0]?.id).toBe("near");
  });
});

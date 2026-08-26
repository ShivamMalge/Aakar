// Deterministic screen-space label layout (ruling 8).
//
// At 5–13 parts, billboarding a label at each part's centroid is legible. At the schema's
// 40-part cap it is not: the neuron stress fixture produced overlapping stacks along the
// axon where four myelin sheaths, three nodes of Ranvier and two Schwann nuclei compete
// for the same strip of screen.
//
// This matters beyond looks. In Phase 3 these captures feed the VLM critic, and label
// collisions are the most visually wrong thing in frame — a critic asked to judge
// structure will spend both repair rounds on cosmetics while real errors pass unexamined.
// Ruling 7 splits the capture path so the critic sees unlabeled frames; this makes the
// labeled frame worth showing a human.
//
// The layout is a pure function of its inputs — no three.js, no DOM — so it is unit
// testable and produces the same frame every time, which byte-stable replay needs (3.7).

export type LabelImportance = "core" | "secondary";

export type LabelCandidate = {
  id: string;
  text: string;
  importance: LabelImportance;
  /** Anchor in screen pixels, origin top-left. */
  anchorX: number;
  anchorY: number;
  /** Distance from camera; nearer labels win ties. */
  depth: number;
  /** True when every sample of the part is behind other geometry. */
  occluded: boolean;
  width: number;
  height: number;
};

export type LabelPlacement = {
  id: string;
  text: string;
  /** Top-left of the label box, screen pixels. */
  x: number;
  y: number;
  width: number;
  height: number;
  anchorX: number;
  anchorY: number;
  /** True when the label sits away from its anchor and needs a leader line. */
  needsLeader: boolean;
};

export type LabelLayout = {
  placed: LabelPlacement[];
  /** Ids with no room, or fully occluded. */
  dropped: string[];
  droppedOccluded: number;
  droppedForSpace: number;
  droppedByImportance: Record<LabelImportance, number>;
};

export type Viewport = { width: number; height: number };

/** Gap kept between label boxes, and between a box and the viewport edge. */
const PADDING = 4;
/** A label closer than this to its anchor does not need a leader line. */
const LEADER_THRESHOLD = 18;

/**
 * Candidate offsets, tried in order: straight right first (reads best beside a part),
 * then left, then a widening ladder above and below.
 *
 * Deliberately a fixed list rather than a search: the same scene must lay out the same
 * way on every render, and a fixed order is the cheapest way to guarantee that.
 */
function offsets(): Array<[number, number]> {
  const out: Array<[number, number]> = [[12, 0], [-12, 0]];
  for (let ring = 1; ring <= 6; ring++) {
    const dy = ring * 18;
    out.push([12, -dy], [12, dy], [-12, -dy], [-12, dy]);
    out.push([0, -dy], [0, dy]);
  }
  for (let ring = 1; ring <= 4; ring++) {
    const dx = 40 + ring * 34;
    out.push([dx, -ring * 22], [dx, ring * 22], [-dx, -ring * 22], [-dx, ring * 22]);
  }
  return out;
}

const OFFSETS = offsets();

type Rect = { x: number; y: number; width: number; height: number };

function overlaps(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.width + PADDING &&
    a.x + a.width + PADDING > b.x &&
    a.y < b.y + b.height + PADDING &&
    a.y + a.height + PADDING > b.y
  );
}

function insideViewport(rect: Rect, viewport: Viewport): boolean {
  return (
    rect.x >= PADDING &&
    rect.y >= PADDING &&
    rect.x + rect.width <= viewport.width - PADDING &&
    rect.y + rect.height <= viewport.height - PADDING
  );
}

/**
 * Place as many labels as fit, dropping the least important first.
 *
 * Order is importance, then depth. `importance` is the schema's own field (D-006 reserved
 * it with no behaviour; this is the first thing to consume it), so when space runs out it
 * is the secondary parts that lose their labels rather than whichever happened to be
 * last in the array.
 */
export function layoutLabels(
  candidates: readonly LabelCandidate[],
  viewport: Viewport,
): LabelLayout {
  const dropped: string[] = [];
  const droppedByImportance: Record<LabelImportance, number> = { core: 0, secondary: 0 };
  let droppedOccluded = 0;
  let droppedForSpace = 0;

  const visible: LabelCandidate[] = [];
  for (const candidate of candidates) {
    // A part hidden behind other geometry gets no label: pointing at something the
    // reader cannot see is worse than saying nothing.
    if (candidate.occluded) {
      dropped.push(candidate.id);
      droppedByImportance[candidate.importance] += 1;
      droppedOccluded += 1;
      continue;
    }
    visible.push(candidate);
  }

  const ordered = [...visible].sort((a, b) => {
    if (a.importance !== b.importance) return a.importance === "core" ? -1 : 1;
    if (a.depth !== b.depth) return a.depth - b.depth;
    return a.id < b.id ? -1 : 1; // stable, so replay is byte-stable
  });

  const placed: LabelPlacement[] = [];
  const taken: Rect[] = [];

  for (const candidate of ordered) {
    let found: Rect | undefined;

    for (const [dx, dy] of OFFSETS) {
      // Offsets are from the anchor to the label's near edge; a left-hand offset puts
      // the box's right edge there instead, so labels do not sit on their own anchors.
      const x = dx >= 0 ? candidate.anchorX + dx : candidate.anchorX + dx - candidate.width;
      const y = candidate.anchorY + dy - candidate.height / 2;
      const rect = { x, y, width: candidate.width, height: candidate.height };

      if (!insideViewport(rect, viewport)) continue;
      if (taken.some((other) => overlaps(rect, other))) continue;
      found = rect;
      break;
    }

    if (found === undefined) {
      dropped.push(candidate.id);
      droppedByImportance[candidate.importance] += 1;
      droppedForSpace += 1;
      continue;
    }

    // Distance to the box's NEAREST EDGE, not its centre. Measuring to the centre makes
    // a label sitting snugly beside its anchor look displaced by half its own width, so
    // every label would get a leader line and the leaders would themselves be the noise.
    const dx = Math.max(found.x - candidate.anchorX, 0, candidate.anchorX - (found.x + found.width));
    const dy = Math.max(
      found.y - candidate.anchorY,
      0,
      candidate.anchorY - (found.y + found.height),
    );
    const distance = Math.hypot(dx, dy);

    taken.push(found);
    placed.push({
      id: candidate.id,
      text: candidate.text,
      x: found.x,
      y: found.y,
      width: found.width,
      height: found.height,
      anchorX: candidate.anchorX,
      anchorY: candidate.anchorY,
      needsLeader: distance > LEADER_THRESHOLD,
    });
  }

  return { placed, dropped, droppedOccluded, droppedForSpace, droppedByImportance };
}

/** Rough label box for text, used when the DOM has not measured it yet. */
export function estimateLabelSize(text: string): { width: number; height: number } {
  // 6.6 px/char at 11px system-ui, plus the padding in `.part-label`.
  return { width: Math.ceil(text.length * 6.6) + 14, height: 20 };
}

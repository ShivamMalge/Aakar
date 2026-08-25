// Viewer options live here, not in Viewer.tsx.
//
// Viewer.tsx is a "use client" module, so every one of its exports becomes a client
// reference. A server component that reads `DEFAULT_OPTIONS.cutaway` off one of those
// gets "Could not find the module ... in the React Client Manifest" at request time —
// the value simply is not readable on the server. Plain data belongs in a plain module
// that both sides can import.
import type { ExplodeMode } from "../compiler";

export type ViewerOptions = {
  /** Quarter-turn index around Y, so the screenshot harness can name a view (1.6). */
  angle: number;
  /** Hide the control chrome — screenshot mode. */
  shot: boolean;
  cutaway: boolean;
  explode: number;
  explodeMode: ExplodeMode;
  labels: boolean;
};

export const DEFAULT_OPTIONS: ViewerOptions = {
  angle: 0,
  shot: false,
  cutaway: false,
  explode: 0,
  explodeMode: "top-level",
  labels: true,
};

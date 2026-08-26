// Label rendering: projection, occlusion, leader lines (ruling 8).
//
// The layout itself is a pure function in ./labels — this file only supplies it with
// screen-space facts and draws the result. Keeping the two apart is what makes the layout
// unit-testable without a browser, and byte-stable for Phase 3 replay.
"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { CompiledScene } from "@/compiler";

import {
  type LabelCandidate,
  type LabelLayout,
  estimateLabelSize,
  layoutLabels,
} from "./labels";

/** Recompute at most this often. Layout is cheap, but not free at 40 parts. */
const INTERVAL_MS = 90;
/** Samples per part used to decide occlusion. */
const OCCLUSION_SAMPLES = 5;
/** At or below this opacity a part is treated as see-through and does not occlude. */
const OPAQUE_ENOUGH = 0.85;

function firstMaterial(mesh: THREE.Mesh): THREE.Material | undefined {
  const material = mesh.material;
  return Array.isArray(material) ? material[0] : material;
}

function isOpaque(mesh: THREE.Mesh): boolean {
  const one = firstMaterial(mesh);
  if (one === undefined) return true;
  const opacity = (one as THREE.Material & { opacity?: number }).opacity;
  return !one.transparent || (opacity ?? 1) > OPAQUE_ENOUGH;
}

/**
 * Is this point actually drawn, given the mesh's clipping planes?
 *
 * The raycaster knows nothing about clipping — it is a CPU intersection test, while
 * clipping happens per-fragment on the GPU. Without this, cutaway mode reported every
 * interior part as occluded by the shell that had just been cut away: `human_eye` placed
 * 1 label of 12 and `earth_layers` placed 0 of 5, both while plainly visible on screen.
 *
 * three.js discards a fragment when `plane.distanceToPoint(p) < 0`.
 */
function isDrawnAt(mesh: THREE.Mesh, point: THREE.Vector3): boolean {
  const planes = firstMaterial(mesh)?.clippingPlanes;
  if (planes === null || planes === undefined || planes.length === 0) return true;
  return planes.every((plane) => plane.distanceToPoint(point) >= 0);
}

export type LabelState = LabelLayout & { viewport: { width: number; height: number } };

/**
 * Points on a part worth testing for visibility: its centre, plus four spread across its
 * bounding box. A single centre sample calls a ring-shaped part occluded whenever
 * something sits in its hole.
 */
function samplePoints(mesh: THREE.Mesh): THREE.Vector3[] {
  mesh.geometry.computeBoundingBox();
  const box = mesh.geometry.boundingBox;
  const centre = new THREE.Vector3();
  if (box === null) {
    mesh.getWorldPosition(centre);
    return [centre];
  }

  box.getCenter(centre);
  const size = box.getSize(new THREE.Vector3()).multiplyScalar(0.35);
  const local = [
    centre.clone(),
    centre.clone().add(new THREE.Vector3(size.x, 0, 0)),
    centre.clone().add(new THREE.Vector3(-size.x, 0, 0)),
    centre.clone().add(new THREE.Vector3(0, size.y, 0)),
    centre.clone().add(new THREE.Vector3(0, -size.y, 0)),
  ].slice(0, OCCLUSION_SAMPLES);

  return local.map((point) => point.applyMatrix4(mesh.matrixWorld));
}

/**
 * Drives the layout from inside the r3f loop and hands it up as React state.
 *
 * State rather than direct DOM writes: at ~11 fps of layout the render cost is
 * negligible, and it keeps the labels declarative so the capture harness sees them in
 * the DOM rather than in a canvas.
 */
export function LabelDriver({
  scene,
  enabled,
  onLayout,
}: {
  scene: CompiledScene;
  enabled: boolean;
  onLayout: (state: LabelState) => void;
}) {
  const { camera, size } = useThree();
  const raycaster = useMemo(() => new THREE.Raycaster(), []);
  const last = useRef(0);
  const meshes = useMemo(() => [...scene.parts.values()].map((part) => part.mesh), [scene]);

  useFrame(({ clock }) => {
    if (!enabled) return;
    const now = clock.getElapsedTime() * 1000;
    if (now - last.current < INTERVAL_MS) return;
    last.current = now;

    const cameraPosition = camera.getWorldPosition(new THREE.Vector3());
    const candidates: LabelCandidate[] = [];

    for (const [id, compiled] of scene.parts) {
      const { mesh, part } = compiled;
      const samples = samplePoints(mesh);
      const anchorWorld = samples[0];
      if (anchorWorld === undefined) continue;

      // Occluded when every sample is blocked by a *different* part.
      let visibleSamples = 0;
      for (const sample of samples) {
        // A sample on the cut-away side of the plane is not on screen at all.
        if (!isDrawnAt(mesh, sample)) continue;
        const direction = sample.clone().sub(cameraPosition);
        const distance = direction.length();
        if (distance < 1e-6) {
          visibleSamples += 1;
          continue;
        }
        raycaster.set(cameraPosition, direction.normalize());
        raycaster.far = distance - 1e-3;
        const blockers = raycaster.intersectObjects(meshes, false);
        // A see-through part does not hide what is behind it. Without this the soma at
        // 0.45 opacity blanked the labels of every organelle plainly visible inside it —
        // the raycaster has no notion of transparency on its own.
        const blocked = blockers.some((hit) => {
          const other = hit.object as THREE.Mesh;
          return other !== mesh && isOpaque(other) && isDrawnAt(other, hit.point);
        });
        if (!blocked) visibleSamples += 1;
      }

      const projected = anchorWorld.clone().project(camera);
      // Behind the camera, or outside the frustum.
      if (projected.z > 1) continue;

      const anchorX = ((projected.x + 1) / 2) * size.width;
      const anchorY = ((1 - projected.y) / 2) * size.height;
      const { width, height } = estimateLabelSize(part.name);

      candidates.push({
        id,
        text: part.name,
        importance: part.importance === "secondary" ? "secondary" : "core",
        anchorX,
        anchorY,
        depth: cameraPosition.distanceTo(anchorWorld),
        occluded: visibleSamples === 0,
        width,
        height,
      });
    }

    onLayout({
      ...layoutLabels(candidates, { width: size.width, height: size.height }),
      viewport: { width: size.width, height: size.height },
    });
  });

  return null;
}

/** The DOM overlay: leader lines in one SVG, labels as positioned spans. */
export function LabelOverlay({
  state,
  selected,
}: {
  state: LabelState | null;
  selected: string | null;
}) {
  if (state === null) return null;

  return (
    <div className="label-layer" aria-hidden="true">
      <svg
        className="label-leaders"
        width={state.viewport.width}
        height={state.viewport.height}
        viewBox={`0 0 ${state.viewport.width} ${state.viewport.height}`}
      >
        {state.placed
          .filter((placement) => placement.needsLeader)
          .map((placement) => {
            // Meet the box on whichever side faces the anchor, so the line never
            // crosses the text it belongs to.
            const centreX = placement.x + placement.width / 2;
            const endX = placement.anchorX < centreX ? placement.x : placement.x + placement.width;
            const endY = placement.y + placement.height / 2;
            return (
              <line
                key={placement.id}
                x1={placement.anchorX}
                y1={placement.anchorY}
                x2={endX}
                y2={endY}
                className={placement.id === selected ? "leader leader-selected" : "leader"}
              />
            );
          })}
        {state.placed
          .filter((placement) => placement.needsLeader)
          .map((placement) => (
            <circle
              key={`${placement.id}-dot`}
              cx={placement.anchorX}
              cy={placement.anchorY}
              r={2}
              className={placement.id === selected ? "leader-dot leader-selected" : "leader-dot"}
            />
          ))}
      </svg>

      {state.placed.map((placement) => (
        <span
          key={placement.id}
          className={placement.id === selected ? "part-label part-label-selected" : "part-label"}
          style={{ left: `${placement.x}px`, top: `${placement.y}px` }}
        >
          {placement.text}
        </span>
      ))}
    </div>
  );
}

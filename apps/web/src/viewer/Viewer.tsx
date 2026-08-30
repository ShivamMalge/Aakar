"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useCallback, useMemo, useState } from "react";
import * as THREE from "three";

import {
  DEFAULT_FOV,
  type ExplodeMode,
  compile,
  defaultCutaway,
  frameScene,
} from "../compiler";
import type { SceneSpec } from "../scenespec";

import { LabelOverlay, type LabelState } from "./LabelLayer";
import { Scene } from "./Scene";
import { DEFAULT_OPTIONS, type ViewerOptions } from "./options";

function vector(source: readonly number[] | undefined, fallback: [number, number, number]) {
  return new THREE.Vector3(
    source?.[0] ?? fallback[0],
    source?.[1] ?? fallback[1],
    source?.[2] ?? fallback[2],
  );
}



export function Viewer({ spec, options }: { spec: SceneSpec; options?: Partial<ViewerOptions> }) {
  const initial = { ...DEFAULT_OPTIONS, ...options };

  const result = useMemo(() => compile(spec), [spec]);

  // A shelled topic — Earth's layers, an eyeball, a cell — shows nothing but its outer
  // shell from outside, so it opens cut away unless the caller said otherwise (ruling 9).
  // Measured from geometry, not guessed from the topic name, so it stays right for topics
  // that do not exist yet.
  const shouldCutAway = useMemo(() => {
    if (options?.cutaway !== undefined) return options.cutaway;
    if (!result.ok) return DEFAULT_OPTIONS.cutaway;
    const meshes = new Map([...result.scene.parts].map(([id, part]) => [id, part.mesh]));
    return defaultCutaway(spec, meshes);
  }, [options?.cutaway, result, spec]);

  const [labelState, setLabelState] = useState<LabelState | null>(null);
  const [ready, setReady] = useState(false);
  const onReady = useCallback(() => setReady(true), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [labels, setLabels] = useState(initial.labels);
  const [cutaway, setCutaway] = useState(shouldCutAway);
  const [explode, setExplode] = useState(initial.explode);
  const [explodeMode, setExplodeMode] = useState<ExplodeMode>(initial.explodeMode);

  // Framing is derived from the scene's own bounds (ruling 9). camera_hint supplies the
  // direction; the distance is computed, because an authored distance is the one number
  // that cannot be right without knowing the final bounds — the neuron stress fixture
  // cropped at both ends for exactly that reason.
  const framing = useMemo(() => {
    if (!result.ok) return null;
    const meshes = [...result.scene.parts.values()].map((part) => part.mesh);
    return frameScene(spec, meshes, { angle: initial.angle });
  }, [result, spec, initial.angle]);

  if (!result.ok) {
    // 1.1: validation errors are a product surface — Phase 3 feeds them to the repair
    // prompt (D3), so they are shown in full rather than collapsed to "invalid spec".
    return (
      <div className="viewer-error" role="alert">
        <h2>This spec does not compile</h2>
        <ul>
          {result.errors.map((error) => (
            <li key={`${error.path}:${error.message}`}>
              <code>{error.path}</code> — {error.message}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  const { scene } = result;
  const target = framing?.target ?? vector(spec.camera_hint?.look_at, [0, 0, 0]);
  const selectedPart = selected !== null ? scene.parts.get(selected)?.part : undefined;

  return (
    <div className="viewer">
      {/*
        Capture-liveness sentinel (1.6). It exists only when the spec compiled AND the
        scene graph was built and painted, and it carries what was actually rendered —
        so the screenshot harness can check it photographed this topic rather than a
        stale bundle. A bare "ready" flag could not tell those apart.
      */}
      {ready ? (
        <div
          data-scene-sentinel=""
          data-topic={spec.topic}
          data-parts={String(scene.parts.size)}
          data-schema-version={spec.schema_version}
          data-labels-placed={String(labelState?.placed.length ?? 0)}
          data-labels-dropped={String(labelState?.dropped.length ?? 0)}
          data-labels-dropped-occluded={String(labelState?.droppedOccluded ?? 0)}
          data-labels-dropped-for-space={String(labelState?.droppedForSpace ?? 0)}
          /*
            The derived parent relations, carried out for Phase 3 (architect ruling).
            They come from `compile()` — which has already run by the time this renders —
            and NOT from the drawn frame, so a spec too broken to render still yields a
            diagnosis. That is precisely when the repair loop needs one.
          */
          data-relations={JSON.stringify(
            [...scene.parts.values()]
              .filter((part) => part.containment !== undefined)
              .map((part) => ({
                p: part.containment!.partId,
                parent: part.containment!.parentId,
                rel: part.containment!.relation,
                cp: part.containment!.childInParent,
                pc: part.containment!.parentInChild,
                gap: part.containment!.relativeGap,
              })),
          )}
          data-warnings={JSON.stringify(
            result.ok ? result.warnings.map((w) => ({ code: w.code, p: w.partId })) : [],
          )}
          hidden
        />
      ) : null}

      <div className="viewer-canvas">
        <Canvas
          camera={{
            position: (framing?.position ?? new THREE.Vector3(3, 2, 4)).toArray(),
            fov: DEFAULT_FOV,
            // A 40-part neuron is ~6 units across; the default far plane of 2000 is
            // fine, but the near plane has to scale or thin parts z-fight up close.
            near: Math.max((framing?.radius ?? 1) / 100, 0.01),
            far: Math.max((framing?.radius ?? 1) * 20, 100),
          }}
          onCreated={({ gl }) => {
            // Required for the spec's cutaway plane to clip anything (1.3).
            gl.localClippingEnabled = true;
          }}
        >
          <color attach="background" args={["#0f1117"]} />
          <Scene
            scene={scene}
            spec={spec}
            selected={selected}
            hovered={hovered}
            showLabels={labels}
            cutaway={cutaway}
            explode={explode}
            explodeMode={explodeMode}
            onSelect={setSelected}
            onHover={setHovered}
            onReady={onReady}
            onLabelLayout={setLabelState}
            angle={initial.angle}
          />
          <OrbitControls makeDefault target={target.toArray()} enableDamping={false} />
        </Canvas>

        {labels ? <LabelOverlay state={labelState} selected={selected} /> : null}
      </div>

      {initial.shot ? null : (
        <aside className="viewer-panel">
          <h1>{spec.title}</h1>
          <p className="viewer-topic">
            <code>{spec.topic}</code> · {spec.parts.length} parts · schema{" "}
            {spec.schema_version}
          </p>

          <fieldset>
            <legend>View</legend>
            <label>
              <input type="checkbox" checked={labels} onChange={(e) => setLabels(e.target.checked)} />
              Labels
            </label>
            <label>
              <input
                type="checkbox"
                checked={cutaway}
                onChange={(e) => setCutaway(e.target.checked)}
                disabled={spec.cutaway?.enabled !== true}
              />
              Cutaway
              {spec.cutaway?.enabled !== true ? <em> (not in this spec)</em> : null}
            </label>
            <label className="viewer-slider">
              Exploded view
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={explode}
                onChange={(e) => setExplode(Number(e.target.value))}
              />
              <output>{explode.toFixed(2)}</output>
            </label>
            <label>
              Explode mode (G-10)
              <select
                value={explodeMode}
                onChange={(e) => setExplodeMode(e.target.value as ExplodeMode)}
              >
                <option value="top-level">top-level parts carry children</option>
                <option value="per-part">every part independently</option>
              </select>
            </label>
          </fieldset>

          <div className="viewer-selection">
            <h2>Selection</h2>
            {selectedPart === undefined ? (
              <p className="viewer-empty">Click a part.</p>
            ) : (
              <dl>
                <dt>Name</dt>
                <dd>{selectedPart.name}</dd>
                <dt>Id</dt>
                <dd>
                  <code>{selectedPart.id}</code>
                </dd>
                <dt>Geometry</dt>
                <dd>
                  <code>{selectedPart.geometry.type}</code>
                </dd>
                {selectedPart.aliases !== undefined && selectedPart.aliases.length > 0 ? (
                  <>
                    <dt>Aliases</dt>
                    <dd>{selectedPart.aliases.join(", ")}</dd>
                  </>
                ) : null}
                <dt>Provenance</dt>
                <dd>
                  <code>{selectedPart.provenance.chunk_ids.join(", ")}</code>
                </dd>
              </dl>
            )}
            <p className="viewer-note">
              The RAG panel arrives in Phase 2. Phase 1 proves selection, nothing more.
            </p>
          </div>
        </aside>
      )}
    </div>
  );
}

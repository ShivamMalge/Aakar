"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useMemo, useState } from "react";
import * as THREE from "three";

import { type ExplodeMode, compile } from "../compiler";
import type { SceneSpec } from "../scenespec";

import { Scene } from "./Scene";
import { DEFAULT_OPTIONS, type ViewerOptions } from "./options";

function vector(source: readonly number[] | undefined, fallback: [number, number, number]) {
  return new THREE.Vector3(
    source?.[0] ?? fallback[0],
    source?.[1] ?? fallback[1],
    source?.[2] ?? fallback[2],
  );
}

/** camera_hint, spun by `angle` quarter-turns about Y. Deterministic per angle index. */
function cameraPosition(spec: SceneSpec, angle: number): THREE.Vector3 {
  return vector(spec.camera_hint?.position, [3, 2, 4]).applyAxisAngle(
    new THREE.Vector3(0, 1, 0),
    (angle * Math.PI) / 2,
  );
}

export function Viewer({ spec, options }: { spec: SceneSpec; options?: Partial<ViewerOptions> }) {
  const initial = { ...DEFAULT_OPTIONS, ...options };

  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [labels, setLabels] = useState(initial.labels);
  const [cutaway, setCutaway] = useState(initial.cutaway);
  const [explode, setExplode] = useState(initial.explode);
  const [explodeMode, setExplodeMode] = useState<ExplodeMode>(initial.explodeMode);

  const result = useMemo(() => compile(spec), [spec]);

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
  const target = vector(spec.camera_hint?.look_at, [0, 0, 0]);
  const selectedPart = selected !== null ? scene.parts.get(selected)?.part : undefined;

  return (
    <div className="viewer">
      <div className="viewer-canvas">
        <Canvas
          camera={{ position: cameraPosition(spec, initial.angle).toArray(), fov: 45 }}
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
          />
          <OrbitControls makeDefault target={target.toArray()} enableDamping={false} />
        </Canvas>
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

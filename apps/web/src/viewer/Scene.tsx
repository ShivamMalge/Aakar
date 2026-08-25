"use client";

// The rendered scene: the compiled object graph plus the deterministic viewer
// behaviours the spec keeps *out* of the SceneSpec (spec §4) — raycast selection,
// hover outline, label billboards, cutaway, exploded view.
import { Html } from "@react-three/drei";
import { type ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { SceneSpec } from "../scenespec";
import {
  type CompiledPart,
  type CompiledScene,
  type ExplodeMode,
  applyClipping,
  applyExplode,
  clipPlaneFor,
  planExplode,
} from "../compiler";

/** Frames to let three.js settle before the screenshot harness is told to shoot. */
const READY_AFTER_FRAMES = 3;

/** Extra camera distance, in multiples of the rest distance, at full explode. */
const DOLLY_PER_EXPLODE = 0.85;
const ORIGIN = new THREE.Vector3();

const HOVER_EMISSIVE = new THREE.Color("#3d7dd6");
const SELECTED_EMISSIVE = new THREE.Color("#f0a500");
const NO_EMISSIVE = new THREE.Color("#000000");

export type SceneProps = {
  scene: CompiledScene;
  spec: SceneSpec;
  selected: string | null;
  hovered: string | null;
  showLabels: boolean;
  cutaway: boolean;
  explode: number;
  explodeMode: ExplodeMode;
  onSelect: (partId: string | null) => void;
  onHover: (partId: string | null) => void;
};

/** Walk up from the hit object to whichever ancestor carries a part id. */
function partIdOf(object: THREE.Object3D | null): string | null {
  for (let node = object; node !== null; node = node.parent) {
    const id: unknown = node.userData["partId"];
    if (typeof id === "string") return id;
  }
  return null;
}

function LabelBillboard({ compiled }: { compiled: CompiledPart }) {
  const anchor = useRef<THREE.Group>(null);

  // Labels track their part through the exploded view, so the anchor is re-read every
  // frame rather than captured once.
  //
  // The anchor sits on top of the part rather than at its centre. Concentric topics
  // put every part on the same centre — Earth's five layers produced five labels
  // stacked on one pixel — so lifting each by its own radius is what separates them.
  useFrame(() => {
    if (anchor.current === null) return;
    compiled.mesh.getWorldPosition(anchor.current.position);
    anchor.current.position.y += compiled.restRadius;
  });

  return (
    <group ref={anchor}>
      <Html center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
        <span className="part-label">{compiled.part.name}</span>
      </Html>
    </group>
  );
}

/**
 * Pulls the camera back as parts separate.
 *
 * A concentric topic is the hard case: five Earth shells are each nearly as wide as
 * the whole assembly, so any separation that actually separates them overflows the
 * framing camera_hint chose for the rest state. Scaling the distance by the *change*
 * in explode — rather than setting it absolutely — means a reader who has zoomed in
 * keeps their zoom.
 */
function ExplodeDolly({ explode }: { explode: number }) {
  const camera = useThree((state) => state.camera);
  const controls = useThree((state) => state.controls) as { target?: THREE.Vector3 } | null;
  // Starts at 0, not at `explode`, so a URL that loads already-exploded (the screenshot
  // harness does exactly that) still gets its dolly on the first frame.
  const applied = useRef(0);

  useFrame(() => {
    if (applied.current === explode) return;
    const scale = (1 + explode * DOLLY_PER_EXPLODE) / (1 + applied.current * DOLLY_PER_EXPLODE);
    applied.current = explode;
    const target = controls?.target ?? ORIGIN;
    camera.position.sub(target).multiplyScalar(scale).add(target);
  });

  return null;
}

/** Tells the Playwright harness (1.6) the frame is worth capturing. */
function ReadySignal() {
  const frames = useRef(0);
  useFrame(() => {
    frames.current += 1;
    if (frames.current === READY_AFTER_FRAMES) {
      document.body.dataset["sceneReady"] = "true";
    }
  });
  return null;
}

export function Scene(props: SceneProps) {
  const { scene, spec, selected, hovered, showLabels, cutaway, explode, explodeMode } = props;
  const { onSelect, onHover } = props;

  const plan = useMemo(() => planExplode(scene, explodeMode), [scene, explodeMode]);

  useEffect(() => {
    applyClipping(scene, cutaway ? clipPlaneFor(spec) : null);
  }, [scene, spec, cutaway]);

  useEffect(() => {
    applyExplode(scene, plan, explode);
  }, [scene, plan, explode]);

  // Hover and selection are viewer state, not spec state — they only tint emissive.
  useEffect(() => {
    for (const [id, { mesh }] of scene.parts) {
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const material of materials) {
        if (!(material instanceof THREE.MeshStandardMaterial)) continue;
        if (id === selected) material.emissive.copy(SELECTED_EMISSIVE);
        else if (id === hovered) material.emissive.copy(HOVER_EMISSIVE);
        else material.emissive.copy(NO_EMISSIVE);
        material.emissiveIntensity = id === selected ? 0.45 : id === hovered ? 0.3 : 0;
      }
    }
  }, [scene, selected, hovered]);

  const handleClick = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    onSelect(partIdOf(event.object));
  };

  const handleOver = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    onHover(partIdOf(event.object));
  };

  return (
    <>
      <ambientLight intensity={0.75} />
      <directionalLight position={[4, 6, 5]} intensity={1.5} />
      <directionalLight position={[-5, -2, -4]} intensity={0.5} />

      <primitive
        object={scene.root}
        onClick={handleClick}
        onPointerOver={handleOver}
        onPointerOut={() => onHover(null)}
        onPointerMissed={() => onSelect(null)}
      />

      {showLabels
        ? [...scene.parts.values()].map((compiled) => (
            <LabelBillboard key={compiled.part.id} compiled={compiled} />
          ))
        : null}

      <ExplodeDolly explode={explode} />
      <ReadySignal />
    </>
  );
}

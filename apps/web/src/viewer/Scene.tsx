"use client";

// The rendered scene: the compiled object graph plus the deterministic viewer
// behaviours the spec keeps *out* of the SceneSpec (spec §4) — raycast selection,
// hover outline, label billboards, cutaway, exploded view.
import { type ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { SceneSpec } from "../scenespec";
import {
  frameScene,
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

import { LabelDriver, type LabelState } from "./LabelLayer";

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
  /** Fired once the scene graph has been built and painted (capture liveness, 1.6). */
  onReady: () => void;
  /** Screen-space label layout, recomputed inside the r3f loop (ruling 8). */
  onLabelLayout: (state: LabelState) => void;
  /** Quarter-turn index; the rig reframes when it changes. */
  angle: number;
};

/** Walk up from the hit object to whichever ancestor carries a part id. */
function partIdOf(object: THREE.Object3D | null): string | null {
  for (let node = object; node !== null; node = node.parent) {
    const id: unknown = node.userData["partId"];
    if (typeof id === "string") return id;
  }
  return null;
}

/**
 * Reframes using the REAL canvas aspect (R1).
 *
 * `frameScene` takes an aspect with a default of 1280x900, and the Viewer could only
 * supply `angle` — the canvas size is not known until r3f has mounted. So the default was
 * the only value ever used, and a portrait phone would have been framed as landscape and
 * cropped. Exactly the shape agents.md R1 describes: the parameter could be omitted, it
 * always was, and the real value never reached it.
 *
 * Deliberately not on every frame: reframing keyed on spec, angle and aspect means a
 * resize or an orientation change re-fits, while orbiting is left alone.
 */
function CameraRig({ spec, scene, angle }: { spec: SceneSpec; scene: CompiledScene; angle: number }) {
  const { camera, size } = useThree();
  const aspect = size.width / size.height;

  useEffect(() => {
    const meshes = [...scene.parts.values()].map((part) => part.mesh);
    const framing = frameScene(spec, meshes, { angle, aspect });
    camera.position.copy(framing.position);
    camera.lookAt(framing.target);
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.aspect = aspect;
      camera.near = Math.max(framing.radius / 100, 0.01);
      camera.far = Math.max(framing.radius * 20, 100);
    }
    camera.updateProjectionMatrix();
  }, [camera, spec, scene, angle, aspect]);

  return null;
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

/**
 * Tells the Viewer the scene graph is built and painted, so it can emit the capture
 * sentinel (1.6).
 *
 * This fires from inside the r3f render loop, which means it cannot fire unless the
 * canvas actually mounted and drew. A stale client bundle never reaches it — which is
 * the whole point: a broken route used to photograph identically to a working one.
 */
function ReadySignal({ onReady }: { onReady: () => void }) {
  const frames = useRef(0);
  const fired = useRef(false);
  useFrame(() => {
    frames.current += 1;
    if (frames.current >= READY_AFTER_FRAMES && !fired.current) {
      fired.current = true;
      onReady();
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

  // A part that responds to a click should look like it does. The interaction probe
  // reads this back, so "parts are clickable" is checked rather than assumed.
  useEffect(() => {
    document.body.style.cursor = hovered !== null ? "pointer" : "auto";
    return () => {
      document.body.style.cursor = "auto";
    };
  }, [hovered]);

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

      <CameraRig spec={spec} scene={scene} angle={props.angle} />
      <LabelDriver scene={scene} enabled={showLabels} onLayout={props.onLabelLayout} />

      <ExplodeDolly explode={explode} />
      <ReadySignal onReady={props.onReady} />
    </>
  );
}

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { compile } from "./compile";
import { applyClipping, clipPlaneFor } from "./cutaway";
import { applyExplode, planExplode } from "./explode";
import { part, spec } from "./fixture";

function ok(s: Parameters<typeof compile>[0]) {
  const result = compile(s);
  if (!result.ok) throw new Error(`expected compile to succeed: ${JSON.stringify(result.errors)}`);
  return result.scene;
}

describe("compile", () => {
  it("builds one mesh per part", () => {
    const scene = ok(spec([part("eyeball"), part("lens")]));
    expect(scene.parts.size).toBe(2);
    expect(scene.root.children).toHaveLength(2);
  });

  it("returns errors instead of throwing on an invalid graph", () => {
    const result = compile(spec([part("lens", { parent_id: "ghost" })]));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0]?.message).toContain("ghost");
  });

  it("nests a child under its parent's mesh", () => {
    const scene = ok(spec([part("eyeball"), part("lens", { parent_id: "eyeball" })]));
    const lens = scene.parts.get("lens")?.mesh;
    expect(lens?.parent?.name).toBe("eyeball");
    expect(scene.root.children).toHaveLength(1);
  });

  it("wires parents declared after their children", () => {
    const scene = ok(spec([part("lens", { parent_id: "eyeball" }), part("eyeball")]));
    expect(scene.parts.get("lens")?.mesh.parent?.name).toBe("eyeball");
  });

  it("applies position, rotation in degrees, and scale", () => {
    const scene = ok(
      spec([
        part("p", {
          transform: { position: [1, 2, 3], rotation: [0, 0, 90], scale: [1, 1, 0.5] },
        }),
      ]),
    );
    const mesh = scene.parts.get("p")?.mesh;
    expect(mesh?.position.toArray()).toEqual([1, 2, 3]);
    expect(mesh?.rotation.z).toBeCloseTo(Math.PI / 2, 10);
    expect(mesh?.scale.toArray()).toEqual([1, 1, 0.5]);
  });

  it("maps material colour, opacity and roughness", () => {
    const scene = ok(
      spec([part("p", { material: { color: "#cfe8ff", opacity: 0.85, roughness: 0.3 } })]),
    );
    const material = scene.parts.get("p")?.mesh.material as THREE.MeshStandardMaterial;
    expect(`#${material.color.getHexString()}`).toBe("#cfe8ff");
    expect(material.opacity).toBeCloseTo(0.85);
    expect(material.transparent).toBe(true);
    expect(material.roughness).toBeCloseTo(0.3);
  });

  it("leaves a fully opaque material non-transparent", () => {
    const scene = ok(
      spec([part("p", { material: { color: "#ffffff", opacity: 1, roughness: 0.5 } })]),
    );
    const material = scene.parts.get("p")?.mesh.material as THREE.MeshStandardMaterial;
    expect(material.transparent).toBe(false);
  });

  it("tags each mesh with its part id for raycasting", () => {
    const scene = ok(spec([part("retina")]));
    expect(scene.parts.get("retina")?.mesh.userData["partId"]).toBe("retina");
  });

  it("measures a finite centroid and radius", () => {
    const scene = ok(
      spec([
        part("a", { transform: { position: [-2, 0, 0] } }),
        part("b", { transform: { position: [2, 0, 0] } }),
      ]),
    );
    expect(scene.centroid.toArray().every(Number.isFinite)).toBe(true);
    expect(scene.centroid.x).toBeCloseTo(0);
    expect(scene.radius).toBeGreaterThan(0);
  });

  it("disposes geometries and materials", () => {
    const scene = ok(spec([part("a")]));
    let disposed = 0;
    scene.parts.get("a")?.mesh.geometry.addEventListener("dispose", () => {
      disposed += 1;
    });
    scene.dispose();
    expect(disposed).toBe(1);
  });
});

describe("exploded view (1.4)", () => {
  const nested = () =>
    ok(
      spec([
        part("body", { transform: { position: [3, 0, 0] } }),
        part("organ", { parent_id: "body", transform: { position: [1, 0, 0] } }),
        part("other", { transform: { position: [-3, 0, 0] } }),
      ]),
    );

  it("factor 0 restores the spec's own transforms exactly", () => {
    const scene = nested();
    const plan = planExplode(scene, "per-part");
    applyExplode(scene, plan, 0.8);
    applyExplode(scene, plan, 0);
    expect(scene.parts.get("organ")?.mesh.position.toArray()).toEqual([1, 0, 0]);
    expect(scene.parts.get("body")?.mesh.position.toArray()).toEqual([3, 0, 0]);
  });

  it("top-level mode leaves children at rest inside their parent", () => {
    const scene = nested();
    applyExplode(scene, planExplode(scene, "top-level"), 1);
    expect(scene.parts.get("organ")?.mesh.position.toArray()).toEqual([1, 0, 0]);
    expect(scene.parts.get("body")!.mesh.position.x).toBeGreaterThan(3);
  });

  it("per-part mode moves a child to its own offset, not its parent's plus its own", () => {
    const scene = nested();
    const plan = planExplode(scene, "per-part");
    applyExplode(scene, plan, 1);
    scene.root.updateMatrixWorld(true);

    const organ = scene.parts.get("organ")!;
    const expected = organ.restWorldPosition.clone().add(plan.offsets.get("organ")!);
    const actual = organ.mesh.getWorldPosition(new THREE.Vector3());
    expect(actual.distanceTo(expected)).toBeLessThan(1e-6);
  });

  it("separates concentric shells that all sit on the centroid", () => {
    // Earth's layers: every part at the origin, so a radial direction does not exist.
    const scene = ok(
      spec([
        part("core", { geometry: { type: "sphere", radius: 0.4 } }),
        part("mantle", { geometry: { type: "sphere", radius: 0.8 } }),
        part("crust", { geometry: { type: "sphere", radius: 1 } }),
      ]),
    );
    applyExplode(scene, planExplode(scene, "top-level"), 1);
    const ys = ["core", "mantle", "crust"].map((id) => scene.parts.get(id)!.mesh.position.y);
    expect(new Set(ys).size).toBe(3);
    expect(Math.max(...ys)).toBeGreaterThan(0);
  });

  it("is deterministic across repeated plans (D1)", () => {
    const a = planExplode(nested(), "per-part");
    const b = planExplode(nested(), "per-part");
    for (const [id, offset] of a.offsets) {
      expect(offset.toArray()).toEqual(b.offsets.get(id)?.toArray());
    }
  });
});

describe("cutaway (1.3)", () => {
  it("returns null when the topic declares no cutaway", () => {
    expect(clipPlaneFor(spec([part("a")]))).toBeNull();
  });

  it("returns null when cutaway is present but disabled", () => {
    expect(clipPlaneFor(spec([part("a")], { cutaway: { enabled: false } }))).toBeNull();
  });

  it("reads the plane from the spec", () => {
    const plane = clipPlaneFor(
      spec([part("a")], { cutaway: { enabled: true, plane: { normal: [0, 0, 1], constant: 0 } } }),
    );
    expect(plane?.normal.toArray()).toEqual([0, 0, 1]);
  });

  it("defaults the plane when enabled without one", () => {
    const plane = clipPlaneFor(spec([part("a")], { cutaway: { enabled: true } }));
    expect(plane).not.toBeNull();
    expect(plane?.normal.length()).toBeCloseTo(1);
  });

  it("clips every part except the clip_exempt ones", () => {
    const s = spec([part("shell"), part("label", { clip_exempt: true })], {
      cutaway: { enabled: true, plane: { normal: [0, 0, 1], constant: 0 } },
    });
    const scene = ok(s);
    applyClipping(scene, clipPlaneFor(s));
    const shell = scene.parts.get("shell")?.mesh.material as THREE.Material;
    const label = scene.parts.get("label")?.mesh.material as THREE.Material;
    expect(shell.clippingPlanes).toHaveLength(1);
    expect(label.clippingPlanes).toHaveLength(0);
  });

  it("clears clipping when toggled off", () => {
    const s = spec([part("shell")], { cutaway: { enabled: true } });
    const scene = ok(s);
    applyClipping(scene, clipPlaneFor(s));
    applyClipping(scene, null);
    const shell = scene.parts.get("shell")?.mesh.material as THREE.Material;
    expect(shell.clippingPlanes).toHaveLength(0);
  });
});

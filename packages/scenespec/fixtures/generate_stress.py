"""Build the stress fixture: a 40-part neuron at depth 6.

The largest golden spec is 13 parts at depth 4; the schema permits 40. Nothing had ever
exercised the cap, and Phase 3 will generate specs against that cap routinely.

A neuron rather than assorted primitives: it is on the spec's own v1 target list (§1), it
is naturally deep (soma -> hillock -> axon -> terminal -> branch -> bouton -> vesicles)
and naturally repetitive (myelin segments, nodes of Ranvier, boutons), which is exactly
what `instance_of` exists for. It also has to read as a neuron, because the architect
wants it as a design input rather than as a load test.

Parts are authored in WORLD coordinates here and converted to parent-relative on the way
out. Doing it by hand is how nested transforms get silently wrong.

Run:  cd services/api && uv run python ../../packages/scenespec/fixtures/generate_stress.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# specs/golden is the Phase 1 deliverable — exactly three hand-written topics. This is a
# synthetic stress fixture, so it lives alongside rather than inside that set.
OUT = HERE.parent.parent.parent / "specs/stress/neuron.json"
SCHEMA = json.loads((HERE.parent / "scenespec.schema.json").read_text(encoding="utf-8"))
SCHEMA_VERSION = SCHEMA["properties"]["schema_version"]["const"]

Vec3 = tuple[float, float, float]

# Anything with children keeps rotation/scale identity, so a child's local frame is a
# pure translation of its parent's. Rotation is used only on leaves.
PARTS: list[dict[str, Any]] = []


def add(
    part_id: str,
    name: str,
    pos: Vec3,
    geometry: dict[str, Any],
    color: str,
    *,
    parent: str | None = None,
    aliases: list[str] | None = None,
    instance_of: str | None = None,
    rotation: Vec3 | None = None,
    scale: Vec3 | None = None,
    opacity: float | None = None,
    roughness: float | None = None,
    clip_exempt: bool = False,
    importance: str = "core",
    chunks: list[str] | None = None,
    evidence: str | None = None,
) -> None:
    PARTS.append(
        {
            "id": part_id,
            "name": name,
            "world": pos,
            "parent": parent,
            "geometry": geometry,
            "color": color,
            "aliases": aliases,
            "instance_of": instance_of,
            "rotation": rotation,
            "scale": scale,
            "opacity": opacity,
            "roughness": roughness,
            "clip_exempt": clip_exempt,
            "importance": importance,
            "chunks": chunks,
            "evidence": evidence,
        }
    )


def tube(points: list[Vec3], origin: Vec3, radius: float) -> dict[str, Any]:
    """Tube paths are local to the part, so shift world points onto the part origin."""
    return {
        "type": "tube",
        "path": [
            [round(p[0] - origin[0], 4), round(p[1] - origin[1], 4), round(p[2] - origin[2], 4)]
            for p in points
        ],
        "radius": radius,
    }


# --------------------------------------------------------------------- soma
add("soma", "Soma", (0, 0, 0), {"type": "sphere", "radius": 0.5}, "#c9a0dc",
    aliases=["cell body", "perikaryon"], opacity=0.45, roughness=0.6,
    chunks=["c_soma_1", "c_soma_2"], evidence="The soma, or cell body, contains the nucleus.")

add("nucleus", "Nucleus", (0, 0, 0), {"type": "sphere", "radius": 0.22}, "#7b4fa3",
    parent="soma", aliases=["cell nucleus"], opacity=0.8,
    chunks=["c_nuc_1"], evidence="A large, centrally placed nucleus is characteristic.")

add("nucleolus", "Nucleolus", (0.05, 0.03, 0.02), {"type": "sphere", "radius": 0.08},
    "#3f2757", parent="nucleus", aliases=["nucleoli"], chunks=["c_nuc_2"])

add("golgi_apparatus", "Golgi Apparatus", (-0.2, 0.2, 0.06),
    {"type": "lathe", "profile": [[0, -0.05], [0.13, -0.02], [0.13, 0.02], [0, 0.05]],
     "segments": 32},
    "#4fa39b", parent="soma", aliases=["Golgi body"], scale=(1, 1, 0.5),
    chunks=["c_org_1"])

add("nissl_body_1", "Nissl Body", (0.16, -0.24, 0.1),
    {"type": "box", "w": 0.16, "h": 0.05, "d": 0.12}, "#d1795f", parent="soma",
    aliases=["Nissl substance", "chromatophilic substance"], instance_of="Nissl Body",
    rotation=(0, 0, 18), chunks=["c_org_2"],
    evidence="Nissl bodies are stacks of rough endoplasmic reticulum.")

add("nissl_body_2", "Nissl Body", (-0.24, -0.16, -0.1),
    {"type": "box", "w": 0.14, "h": 0.05, "d": 0.1}, "#d1795f", parent="soma",
    aliases=["Nissl substance", "chromatophilic substance"], instance_of="Nissl Body",
    rotation=(0, 0, -24), importance="secondary", chunks=["c_org_2"])

add("mitochondrion_soma", "Mitochondrion", (0.24, 0.2, -0.12),
    {"type": "capsule", "radius": 0.045, "length": 0.12}, "#c25b5b", parent="soma",
    aliases=["mitochondria"], instance_of="Mitochondrion", rotation=(0, 0, 40),
    chunks=["c_org_3"])

add("axon_hillock", "Axon Hillock", (0.52, 0, 0),
    {"type": "cone", "radius": 0.16, "height": 0.22}, "#b98fd0", parent="soma",
    aliases=["initial segment"], rotation=(0, 0, -90), opacity=0.9,
    chunks=["c_axon_1"], evidence="The axon arises from the axon hillock.")

# --------------------------------------------------------------------- axon
AXON_ORIGIN: Vec3 = (0.52, 0, 0)
add("axon", "Axon", AXON_ORIGIN,
    tube([(0.66, 0, 0), (1.3, 0.04, 0), (2.0, -0.03, 0), (2.7, 0.02, 0), (3.3, 0, 0)],
         AXON_ORIGIN, 0.055),
    "#e8d7a0", parent="soma", aliases=["nerve fibre"],
    clip_exempt=True, chunks=["c_axon_1", "c_axon_2"],
    evidence="A single long axon conducts impulses away from the cell body.")

MYELIN_X = [0.95, 1.62, 2.3, 2.95]
for i, x in enumerate(MYELIN_X, start=1):
    add(f"myelin_{i}", "Myelin Sheath", (x, 0.01, 0),
        {"type": "cylinder", "r_top": 0.12, "r_bottom": 0.12, "height": 0.5},
        "#f2e9c9", parent="axon", aliases=["myelin", "medullary sheath"],
        instance_of="Myelin Sheath", rotation=(0, 0, 90), opacity=0.85,
        chunks=["c_mye_1"] + (["c_mye_2"] if i == 1 else []),
        evidence="Myelin insulates the axon." if i == 1 else None)

NODE_X = [1.28, 1.96, 2.63]
for i, x in enumerate(NODE_X, start=1):
    add(f"node_of_ranvier_{i}", "Node of Ranvier", (x, 0.01, 0),
        {"type": "torus", "radius": 0.075, "tube": 0.022}, "#8a6f3c", parent="axon",
        aliases=["nodal gap", "neurofibril node"], instance_of="Node of Ranvier",
        rotation=(0, 90, 0), chunks=["c_mye_3"],
        evidence="Gaps in the sheath are the nodes of Ranvier." if i == 1 else None)

for i, x in enumerate([1.0, 2.35], start=1):
    add(f"schwann_nucleus_{i}", "Schwann Cell Nucleus", (x, 0.13, 0.02),
        {"type": "sphere", "radius": 0.042}, "#b3a06a", parent="axon",
        aliases=["neurolemmocyte nucleus"], instance_of="Schwann Cell Nucleus",
        importance="secondary", chunks=["c_mye_4"])

add("mitochondrion_axon", "Mitochondrion", (1.62, -0.09, 0.03),
    {"type": "capsule", "radius": 0.028, "length": 0.09}, "#c25b5b", parent="axon",
    aliases=["mitochondria"], instance_of="Mitochondrion", rotation=(0, 0, 8),
    importance="secondary", chunks=["c_org_3"])

# ----------------------------------------------------------------- terminals
TRUNK_ORIGIN: Vec3 = (3.3, 0, 0)
add("axon_terminal_trunk", "Axon Terminal", TRUNK_ORIGIN,
    tube([(3.3, 0, 0), (3.55, 0, 0)], TRUNK_ORIGIN, 0.05), "#e8d7a0",
    parent="axon", aliases=["telodendron", "terminal arborisation"],
    chunks=["c_term_1"], evidence="The axon ends in a branching terminal arborisation.")

BRANCH_ENDS: list[Vec3] = [(3.95, 0.26, 0.05), (4.0, 0.0, -0.06), (3.93, -0.26, 0.04)]
for i, end in enumerate(BRANCH_ENDS, start=1):
    add(f"terminal_branch_{i}", "Terminal Branch", TRUNK_ORIGIN,
        tube([(3.55, 0, 0), ((3.55 + end[0]) / 2, end[1] * 0.6, end[2] * 0.6), end],
             TRUNK_ORIGIN, 0.03),
        "#e8d7a0", parent="axon_terminal_trunk", aliases=["terminal branch"],
        instance_of="Terminal Branch", importance="secondary", chunks=["c_term_1"])

for i, end in enumerate(BRANCH_ENDS, start=1):
    add(f"bouton_{i}", "Synaptic Bouton", (end[0] + 0.06, end[1], end[2]),
        {"type": "sphere", "radius": 0.075}, "#e0794f", parent=f"terminal_branch_{i}",
        aliases=["synaptic knob", "terminal bouton", "end bulb"],
        instance_of="Synaptic Bouton", chunks=["c_syn_1", "c_syn_2"],
        evidence="Each branch ends in a synaptic knob." if i == 1 else None)

for i in (1, 2):
    end = BRANCH_ENDS[i - 1]
    add(f"vesicle_cluster_{i}", "Synaptic Vesicles", (end[0] + 0.08, end[1], end[2]),
        {"type": "sphere", "radius": 0.032}, "#f6c453", parent=f"bouton_{i}",
        aliases=["synaptic vesicle", "neurotransmitter vesicle"],
        instance_of="Synaptic Vesicles", chunks=["c_syn_3"],
        evidence="Vesicles in the knob store neurotransmitter." if i == 1 else None)

cleft = BRANCH_ENDS[0]
add("synaptic_cleft", "Synaptic Cleft", (cleft[0] + 0.15, cleft[1], cleft[2]),
    {"type": "extrude", "shape": [[-0.07, -0.07], [0.07, -0.07], [0.07, 0.07], [-0.07, 0.07]],
     "depth": 0.012},
    "#9fd3c7", parent="bouton_1", aliases=["synapse", "synaptic gap"],
    rotation=(0, 90, 0), opacity=0.55, chunks=["c_syn_4"],
    evidence="A narrow cleft separates the knob from the next neuron.")

# ----------------------------------------------------------------- dendrites
TRUNKS: list[tuple[str, Vec3, Vec3]] = [
    ("dendrite_trunk_1", (-0.45, 0.2, 0), (-1.15, 0.62, 0.05)),
    ("dendrite_trunk_2", (-0.44, -0.24, 0), (-1.1, -0.7, -0.05)),
]
for trunk_id, start, end in TRUNKS:
    add(trunk_id, "Dendrite", start,
        tube([start, ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, 0), end], start, 0.05),
        "#c9a0dc", parent="soma", aliases=["dendrites", "dendritic trunk"],
        instance_of="Dendrite", chunks=["c_den_1"],
        evidence="Dendrites receive impulses and carry them toward the cell body."
        if trunk_id.endswith("1") else None)

BRANCHES: list[tuple[str, str, Vec3, Vec3]] = [
    ("dendrite_branch_1", "dendrite_trunk_1", (-1.15, 0.62, 0.05), (-1.7, 0.95, 0.12)),
    ("dendrite_branch_2", "dendrite_trunk_1", (-1.15, 0.62, 0.05), (-1.62, 0.32, -0.1)),
    ("dendrite_branch_3", "dendrite_trunk_2", (-1.1, -0.7, -0.05), (-1.68, -1.0, 0.08)),
]
for branch_id, parent, start, end in BRANCHES:
    add(branch_id, "Dendritic Branch", start, tube([start, end], start, 0.032), "#c9a0dc",
        parent=parent, aliases=["dendrite branch"], instance_of="Dendritic Branch",
        importance="secondary", chunks=["c_den_1"])

TWIGS: list[tuple[str, str, Vec3, Vec3]] = [
    ("dendrite_twig_1", "dendrite_branch_1", (-1.7, 0.95, 0.12), (-2.05, 1.2, 0.16)),
    ("dendrite_twig_2", "dendrite_branch_3", (-1.68, -1.0, 0.08), (-2.02, -1.26, 0.12)),
]
for twig_id, parent, start, end in TWIGS:
    add(twig_id, "Dendritic Twig", start, tube([start, end], start, 0.02), "#c9a0dc",
        parent=parent, aliases=["terminal dendrite"], instance_of="Dendritic Twig",
        importance="secondary", chunks=["c_den_2"])

SPINES: list[tuple[str, str, Vec3]] = [
    ("dendritic_spine_1", "dendrite_twig_1", (-2.11, 1.26, 0.17)),
    ("dendritic_spine_2", "dendrite_twig_2", (-2.08, -1.32, 0.13)),
]
for spine_id, parent, pos in SPINES:
    add(spine_id, "Dendritic Spine", pos,
        {"type": "capsule", "radius": 0.022, "length": 0.05}, "#b284c9", parent=parent,
        aliases=["spine", "dendritic protrusion"], instance_of="Dendritic Spine",
        rotation=(0, 0, 35) if spine_id.endswith("2") else None, chunks=["c_den_3"],
        evidence="Spines are small protrusions that receive synaptic contacts."
        if spine_id.endswith("1") else None)

add("spine_head_1", "Spine Head", (-2.15, 1.31, 0.18),
    {"type": "sphere", "radius": 0.036}, "#9a6bb8", parent="dendritic_spine_1",
    aliases=["spine apex"], instance_of="Spine Head", chunks=["c_den_3"])

add("postsynaptic_density_1", "Postsynaptic Density", (-2.19, 1.34, 0.18),
    {"type": "extrude", "shape": [[-0.026, -0.026], [0.026, -0.026], [0.026, 0.026],
                                  [-0.026, 0.026]], "depth": 0.008},
    "#6d4a86", parent="spine_head_1", aliases=["PSD", "postsynaptic membrane"],
    rotation=(0, 68, 0), chunks=["c_den_4"],
    evidence="The postsynaptic density is the receiving face of the synapse.")


def build() -> dict[str, Any]:
    world = {p["id"]: p["world"] for p in PARTS}
    out_parts: list[dict[str, Any]] = []

    for p in PARTS:
        parent = p["parent"]
        anchor = world[parent] if parent is not None else (0.0, 0.0, 0.0)
        local = [round(p["world"][i] - anchor[i], 4) for i in range(3)]

        part: dict[str, Any] = {"id": p["id"], "name": p["name"]}
        if p["aliases"]:
            part["aliases"] = p["aliases"]
        if p["instance_of"]:
            part["instance_of"] = p["instance_of"]
        if parent is not None:
            part["parent_id"] = parent
        part["geometry"] = p["geometry"]

        transform: dict[str, Any] = {"position": local}
        if p["rotation"]:
            transform["rotation"] = list(p["rotation"])
        if p["scale"]:
            transform["scale"] = list(p["scale"])
        part["transform"] = transform

        material: dict[str, Any] = {"color": p["color"]}
        if p["opacity"] is not None:
            material["opacity"] = p["opacity"]
        if p["roughness"] is not None:
            material["roughness"] = p["roughness"]
        part["material"] = material

        if p["clip_exempt"]:
            part["clip_exempt"] = True
        if p["importance"] != "core":
            part["importance"] = p["importance"]

        # Mixed provenance strength. The schema requires >= 1 chunk id, so a part with
        # *no* provenance is not expressible — "weak" here means a single citation and
        # no quoted evidence, which is the weakest a spec can legally be.
        provenance: dict[str, Any] = {"chunk_ids": p["chunks"] or ["c_general"]}
        if p["evidence"]:
            provenance["evidence"] = p["evidence"]
        part["provenance"] = provenance

        out_parts.append(part)

    return {
        "schema_version": SCHEMA_VERSION,
        "topic": "neuron",
        "title": "The Neuron",
        "parts": out_parts,
        "cutaway": {"enabled": True, "plane": {"normal": [0, 0, -1], "constant": 0}},
        # The neuron spans roughly x=-2.2 to x=4.0. The first camera_hint framed it like a
        # 1-unit topic and cropped both ends; a wide assembly needs the hint to reflect its
        # own extent. Worth noting for Phase 3 — a generator copying a golden spec's
        # camera_hint onto a much larger topic will crop it the same way.
        "camera_hint": {"position": [0.9, 1.15, 8.6], "look_at": [0.9, -0.05, 0]},
    }


# NOTE (ruling 11): an earlier draft asserted here that no part with children may carry a
# rotation or scale. That was wrong and has been removed. Rotating a parent to carry its
# subtree is correct scene-graph behaviour and a legitimate authoring tool; the axon
# hillock was an authoring error, not a semantic one. The compiler now emits a *warning*
# for it instead (see apps/web/src/compiler/containment.ts), and this generator authors in
# world coordinates purely as a convenience, which is why it keeps its own parents
# translation-only.


def main() -> int:
    spec = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ids = {p["id"] for p in spec["parts"]}
    parent_of = {p["id"]: p.get("parent_id") for p in spec["parts"]}

    def depth(part_id: str) -> int:
        d, node = 0, parent_of.get(part_id)
        while node is not None:
            d += 1
            node = parent_of.get(node)
        return d

    deepest = max(ids, key=depth)
    geometries = {p["geometry"]["type"] for p in spec["parts"]}
    groups: dict[str, int] = {}
    for p in spec["parts"]:
        if "instance_of" in p:
            groups[p["instance_of"]] = groups.get(p["instance_of"], 0) + 1

    print(f"wrote {OUT.relative_to(OUT.parents[2])}")
    print(f"  parts            : {len(spec['parts'])}")
    print(f"  max depth        : {depth(deepest)}  (deepest: {deepest})")
    print(f"  geometry types   : {len(geometries)}/9  {sorted(geometries)}")
    print(f"  instance_of      : {len(groups)} groups, {sum(groups.values())} parts")
    print(f"  clip_exempt      : {[p['id'] for p in spec['parts'] if p.get('clip_exempt')]}")
    weak = sum(1 for p in spec["parts"] if "evidence" not in p["provenance"])
    print(f"  provenance       : {len(spec['parts']) - weak} with evidence, {weak} without")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

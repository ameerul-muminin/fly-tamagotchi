"""Build the dashboard's 3D fly from DeepMind/Janelia's flybody model.

Source: TuragaLab/flybody (Apache-2.0), `flybody/fruitfly/assets/`: `fruitfly.xml`
(MuJoCo MJCF: body tree, joints, materials) and one OBJ mesh per part. The model is
from Vaxenburg et al. 2025, "Whole-body physics simulation of fruit fly locomotion",
Nature (doi:10.1038/s41586-025-09029-4). Pinned to FLYBODY_COMMIT below.

What this does:
1. Downloads the XML and the OBJ meshes it names into `data/flybody/` (about 140 MB,
   once; `data/` is gitignored, nothing here is committed).
2. Simplifies each mesh to a triangle budget (fast-simplification, quadric decimation).
3. Writes `data/fly_model/fly.glb` (full detail, for GPUs) and `fly_low.glb` (a quarter
   of the triangles and no bristles, for software renderers): one glTF node per MJCF body (named like the body,
   posed by its `pos`/`quat`), a child node per visual mesh geom, and the MJCF joints
   (name, axis, rest angle) in the scene's `extras` so the page can bend the legs,
   wings and proboscis. Units are the model's: centimetres (1 mm = 0.1). No normals are
   stored (the page computes smooth ones), which keeps the file small.

Display only: the fly's behaviour still comes from the brain (tick.game.eating).

Usage: python -m server.fly_model   (then restart the server; the dashboard picks it up)
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from brain.config import DATA_DIR

FLYBODY_REPO = "TuragaLab/flybody"
FLYBODY_COMMIT = "d015e9bfe441bd90ae431bac24c55cb74bdbce26"  # main, 2025-07-30
FLYBODY_DIR = "flybody/fruitfly/assets"
SRC_DIR = DATA_DIR / "flybody"
OUT_PATH = DATA_DIR / "fly_model" / "fly.glb"
OUT_LOW_PATH = DATA_DIR / "fly_model" / "fly_low.glb"

# Triangle budget per mesh (after simplification). Bristle meshes ("black",
# "bristle-brown") are thin tubes that collapse when simplified hard, so they keep more.
TRIANGLES = {
    "default": 1500,
    "head": 5000, "head_red": 8000, "thorax": 6000,
    "wing_left_membrane": 600, "wing_right_membrane": 600,
    "wing_left_brown": 3000, "wing_right_brown": 3000,
}
BRISTLE_FRACTION = 0.5        # bristles keep this share of their triangles...
BRISTLE_MAX = 12000           # ...but no more than this

# Level of detail: triangle budgets are multiplied by `scale`; `bristles` False leaves
# the bristle meshes out. "low" is for software WebGL (SwiftShader), where every
# triangle costs CPU time the brain simulation also needs.
LODS = {
    "high": {"out": OUT_PATH, "scale": 1.0, "bristles": True},
    "low": {"out": OUT_LOW_PATH, "scale": 0.25, "bristles": False},
}
BRISTLE_MATERIALS = ("black", "bristle-brown")
MIN_TRIANGLES = 120           # never simplify a mesh below this

# Materials by MJCF name. The page (fly_model3d.js) sets the final colors by name; these
# are close defaults so the GLB also looks right in any glTF viewer.
MATERIALS = {
    "body":          {"color": [0.80, 0.56, 0.30, 1.0], "roughness": 0.55},
    "lower":         {"color": [0.88, 0.72, 0.50, 1.0], "roughness": 0.6},
    "red":           {"color": [0.62, 0.03, 0.02, 1.0], "roughness": 0.35},
    "ocelli":        {"color": [0.13, 0.05, 0.02, 1.0], "roughness": 0.3},
    "black":         {"color": [0.08, 0.05, 0.03, 1.0], "roughness": 0.5},
    "bristle-brown": {"color": [0.10, 0.06, 0.03, 1.0], "roughness": 0.5},
    "brown":         {"color": [0.30, 0.17, 0.08, 1.0], "roughness": 0.5},
    "membrane":      {"color": [0.86, 0.90, 0.95, 0.28], "roughness": 0.15, "blend": True},
}


def _raw(path: str) -> str:
    return f"https://github.com/{FLYBODY_REPO}/raw/{FLYBODY_COMMIT}/{FLYBODY_DIR}/{path}"


def _fetch(name: str) -> Path:
    """Download one asset file into data/flybody/ unless it is already there."""
    dest = SRC_DIR / name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  download  {name}")
    urllib.request.urlretrieve(_raw(name), tmp)
    tmp.replace(dest)
    return dest


# ---------------------------------------------------------------------------
# MJCF reading
# ---------------------------------------------------------------------------

def _floats(s: str | None, default: list[float]) -> list[float]:
    return [float(x) for x in s.split()] if s else list(default)


@dataclass
class Defaults:
    """MJCF default classes: class name -> {tag: attributes}, parents merged in."""

    classes: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)

    @classmethod
    def parse(cls, root: ET.Element) -> "Defaults":
        d = cls()

        def walk(el: ET.Element, inherited: dict[str, dict[str, str]]) -> None:
            name = el.get("class", "main")
            own = {tag: dict(attrs) for tag, attrs in inherited.items()}
            for child in el:
                if child.tag != "default":
                    own.setdefault(child.tag, {}).update(child.attrib)
            d.classes[name] = own
            for child in el:
                if child.tag == "default":
                    walk(child, own)

        top = root.find("default")
        if top is not None:
            walk(top, {})
        return d

    def attrs(self, el: ET.Element, active_class: str) -> dict[str, str]:
        """Attributes of `el` with its class defaults filled in."""
        cls = el.get("class", active_class)
        out = dict(self.classes.get(cls, {}).get(el.tag, {}))
        out.update(el.attrib)
        return out


@dataclass
class Joint:
    name: str
    body: str
    axis: list[float]
    rest: float          # springref, the model's spring rest angle (rad)
    range: list[float]


@dataclass
class Geom:
    name: str
    body: str
    mesh: str
    material: str
    pos: list[float]
    quat: list[float]    # w x y z


@dataclass
class Body:
    name: str
    parent: str | None
    pos: list[float]
    quat: list[float]    # w x y z


def read_mjcf(xml_path: Path) -> tuple[list[Body], list[Joint], list[Geom], dict[str, str], float]:
    """Bodies (parents first), joints, visual mesh geoms, mesh name -> file, mesh scale."""
    root = ET.parse(xml_path).getroot()
    defaults = Defaults.parse(root)
    meshes = {m.get("name"): m.get("file") for m in root.iter("mesh") if m.get("file")}
    scale = _floats(defaults.classes.get("main", {}).get("mesh", {}).get("scale"), [1, 1, 1])[0]

    bodies: list[Body] = []
    joints: list[Joint] = []
    geoms: list[Geom] = []

    def walk(el: ET.Element, parent: str | None, active: str) -> None:
        name = el.get("name")
        bodies.append(Body(name, parent, _floats(el.get("pos"), [0, 0, 0]),
                           _floats(el.get("quat"), [1, 0, 0, 0])))
        child_active = el.get("childclass", active)
        for c in el:
            if c.tag == "joint":
                a = defaults.attrs(c, child_active)
                if a.get("type", "hinge") != "hinge":
                    continue
                joints.append(Joint(a["name"], name, _floats(a.get("axis"), [0, 0, 1]),
                                    float(a.get("springref", 0)),
                                    _floats(a.get("range"), [0, 0])))
            elif c.tag == "geom":
                a = defaults.attrs(c, child_active)
                if a.get("type", "sphere") != "mesh" or "mesh" not in a:
                    continue
                geoms.append(Geom(a["name"], name, a["mesh"], a.get("material", "body"),
                                  _floats(a.get("pos"), [0, 0, 0]),
                                  _floats(a.get("quat"), [1, 0, 0, 0])))
            elif c.tag == "body":
                walk(c, name, child_active)

    world = root.find("worldbody")
    for b in world.findall("body"):
        walk(b, None, "main")
    return bodies, joints, geoms, meshes, scale


# ---------------------------------------------------------------------------
# Meshes
# ---------------------------------------------------------------------------

def read_obj(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (n, 3) and triangles (m, 3) of an OBJ file (polygons fanned)."""
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                idx = [int(tok.split("/")[0]) for tok in line.split()[1:]]
                idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
                for k in range(1, len(idx) - 1):
                    faces.append([idx[0], idx[k], idx[k + 1]])
    v = np.asarray(verts, np.float32)
    f = np.asarray(faces, np.int32)
    # The flybody OBJs store three vertices per triangle; weld shared corners so the
    # mesh is connected (simplification and smooth normals need that).
    v, inverse = np.unique(np.round(v, 5), axis=0, return_inverse=True)
    f = inverse.reshape(-1)[f]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    return v.astype(np.float32), f.astype(np.int32)


def simplify(v: np.ndarray, f: np.ndarray, target: int) -> tuple[np.ndarray, np.ndarray]:
    """Quadric-decimate to about `target` triangles (unchanged if already smaller)."""
    if len(f) <= target:
        return v, f
    import fast_simplification
    v2, f2 = fast_simplification.simplify(v, f, target_reduction=1 - target / len(f))
    return v2.astype(np.float32), f2.astype(np.int32)


def budget(mesh_name: str, material: str, n_tri: int, scale: float = 1.0) -> int:
    """Triangle budget for one mesh at a level-of-detail `scale`."""
    if mesh_name in TRIANGLES:
        b = TRIANGLES[mesh_name]
    elif material in BRISTLE_MATERIALS:
        b = min(BRISTLE_MAX, max(TRIANGLES["default"], BRISTLE_FRACTION * n_tri))
    else:
        b = TRIANGLES["default"]
    return int(max(MIN_TRIANGLES, b * scale))


# ---------------------------------------------------------------------------
# glTF writer
# ---------------------------------------------------------------------------

def _q_gltf(q: list[float]) -> list[float]:
    """MJCF quaternion (w x y z) -> glTF (x y z w), normalized."""
    w, x, y, z = q
    n = (w * w + x * x + y * y + z * z) ** 0.5 or 1.0
    return [x / n, y / n, z / n, w / n]


class GlbWriter:
    def __init__(self) -> None:
        self.bin = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def add(self, arr: np.ndarray, target: int, ctype: int, typ: str, minmax: bool = False) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        data = arr.tobytes()
        self.bin += data
        self.views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        acc = {"bufferView": len(self.views) - 1, "componentType": ctype,
               "count": int(arr.shape[0]) if typ != "SCALAR" else int(arr.size), "type": typ}
        if minmax:
            acc["min"] = arr.min(axis=0).tolist()
            acc["max"] = arr.max(axis=0).tolist()
        self.accessors.append(acc)
        return len(self.accessors) - 1


def build(lod: str = "high") -> dict:
    """Download (if needed) and build one level of detail. Returns a small summary."""
    out, lod_scale, bristles = LODS[lod]["out"], LODS[lod]["scale"], LODS[lod]["bristles"]
    xml_path = _fetch("fruitfly.xml")
    bodies, joints, geoms, mesh_files, scale = read_mjcf(xml_path)

    w = GlbWriter()
    mat_names = list(MATERIALS)
    materials = []
    for name in mat_names:
        m = MATERIALS[name]
        entry = {"name": name, "pbrMetallicRoughness": {
            "baseColorFactor": m["color"], "metallicFactor": 0.0, "roughnessFactor": m["roughness"]}}
        if m.get("blend"):
            entry["alphaMode"] = "BLEND"
            entry["doubleSided"] = True
        materials.append(entry)

    nodes: list[dict] = []
    meshes: list[dict] = []
    body_node: dict[str, int] = {}
    tri_in = tri_out = 0

    for b in bodies:
        body_node[b.name] = len(nodes)
        nodes.append({"name": b.name, "translation": b.pos, "rotation": _q_gltf(b.quat), "children": []})
        if b.parent is not None:
            nodes[body_node[b.parent]]["children"].append(body_node[b.name])

    for g in geoms:
        if not bristles and g.material in BRISTLE_MATERIALS:
            continue
        v, f = read_obj(_fetch(mesh_files[g.mesh]))
        tri_in += len(f)
        v, f = simplify(v, f, budget(g.mesh, g.material, len(f), lod_scale))
        tri_out += len(f)
        v = (v * scale).astype(np.float32)
        pa = w.add(v, 34962, 5126, "VEC3", minmax=True)
        idx = f.astype(np.uint16 if v.shape[0] < 65536 else np.uint32).ravel()
        ia = w.add(idx, 34963, 5123 if idx.dtype == np.uint16 else 5125, "SCALAR")
        meshes.append({"name": g.name, "primitives": [{
            "attributes": {"POSITION": pa}, "indices": ia,
            "material": mat_names.index(g.material if g.material in MATERIALS else "body")}]})
        node = len(nodes)
        nodes.append({"name": g.name, "mesh": len(meshes) - 1,
                      "translation": g.pos, "rotation": _q_gltf(g.quat)})
        nodes[body_node[g.body]]["children"].append(node)
        print(f"  {lod:4s} mesh {g.name:32s} {len(f):6d} triangles")

    for nd in nodes:
        if not nd.get("children"):
            nd.pop("children", None)

    roots = [body_node[b.name] for b in bodies if b.parent is None]
    extras = {
        "source": f"{FLYBODY_REPO}@{FLYBODY_COMMIT[:7]}:{FLYBODY_DIR} (Apache-2.0); "
                  "Vaxenburg et al. 2025, Nature, doi:10.1038/s41586-025-09029-4",
        "units": "cm (1 mm = 0.1)",
        "lod": lod,
        "up": "+z (MuJoCo)",
        "forward": "+x (head)",
        "joints": [{"name": j.name, "body": j.body, "axis": j.axis, "rest": j.rest,
                    "range": j.range} for j in joints],
    }
    gltf = {
        "asset": {"version": "2.0", "generator": "server/fly_model.py", "extras": extras},
        "scene": 0,
        "scenes": [{"nodes": roots, "extras": extras}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": w.accessors,
        "bufferViews": w.views,
        "buffers": [{"byteLength": len(w.bin)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    binary = bytes(w.bin) + b"\0" * ((4 - len(w.bin) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(binary), 0x004E4942) + binary)
    summary = {"path": str(out), "bytes": total, "meshes": len(meshes), "bodies": len(bodies),
               "joints": len(joints), "triangles_in": tri_in, "triangles_out": tri_out,
               "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    return summary


def main() -> int:
    for lod in LODS:
        print(json.dumps(build(lod), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

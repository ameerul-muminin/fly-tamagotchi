"""3D neuron positions for the dashboard brain view.

Source: the FlyWire annotation table (`data/flywire_annotations_783.tsv`, see
`brain/config.py` DATA_FILES). Its `pos_x, pos_y, pos_z` columns "are anchor
coordinates in 4x4x40nm voxel space (typically on the backbone of the neuron)"
(flyconnectome/flywire_annotations, supplemental_files/README.md, same pinned commit).

The table uses release-783 root IDs and the brain uses release 630. As in
`brain/neuron_groups.py`, a root ID names one fixed segmentation, so an ID found in
both releases is the same neuron. Neurons edited between 630 and 783 got new IDs;
they have no position here and are left out of the 3D view (never guessed).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from brain.config import DATA_FILES, POSITIONS

ANNOTATIONS = DATA_FILES["annotations"]


@dataclass(frozen=True)
class Positions:
    """Positions of the placeable neurons, in the order of `ids`."""

    ids: np.ndarray        # int64 root IDs that have a position
    xyz_um: np.ndarray     # (n, 3) float, micrometres, FlyWire axes
    n_requested: int       # how many IDs were asked for

    @property
    def n_missing(self) -> int:
        return self.n_requested - int(self.ids.size)


@lru_cache(maxsize=1)
def _annotation_positions() -> pd.DataFrame:
    """root_id -> (pos_x, pos_y, pos_z) voxel coordinates, one row per root ID."""
    return _annotation_table()[list(POSITIONS.columns)]


def neuron_positions(ids: Iterable[int]) -> Positions:
    """Positions (µm) of the given v630 root IDs that exist unchanged in the annotations.

    Args:
        ids: FlyWire root IDs of the running brain.
    """
    ids = np.asarray(list(ids), dtype=np.int64)
    table = _annotation_positions()
    found = ids[np.isin(ids, table.index.to_numpy())]
    vox = table.loc[found, list(POSITIONS.columns)].to_numpy(dtype=float)
    return Positions(found, vox * np.asarray(POSITIONS.voxel_um), int(ids.size))


def positions_payload(ids: Iterable[int], groups: dict[str, list[str]] | None = None) -> dict:
    """JSON body of `GET /api/positions` (IDs as strings, flat xyz list in µm)."""
    p = neuron_positions(ids)
    placed = set(p.ids.astype(str).tolist())
    xyz = np.round(p.xyz_um, POSITIONS.decimals)
    return {
        "units": "um",
        "axes": "FlyWire voxel axes scaled to um (x, y = EM image plane, y grows down; "
                "z = section axis)",
        "source": f"{ANNOTATIONS.repo}@{ANNOTATIONS.commit[:7]}:{ANNOTATIONS.repo_path} "
                  f"columns {', '.join(POSITIONS.columns)} (4x4x40 nm voxels); "
                  "v630 IDs unchanged in v783 only",
        "n_neurons": p.n_requested,
        "n_placed": int(p.ids.size),
        "ids": p.ids.astype(str).tolist(),
        "xyz": xyz.ravel().tolist(),
        "groups_unplaced": {g: [i for i in gids if i not in placed]
                            for g, gids in (groups or {}).items()},
    }


# ---------------------------------------------------------------------------
# Whole-brain atlas: every neuron in the annotation table, drawn as the backdrop of the
# 3D view. Only the running brain's neurons can spike; the rest are anatomy context.
# ---------------------------------------------------------------------------
ATLAS_INFO_COLUMNS = ("cell_type", "side", "top_nt", "super_class", "cell_class")


@lru_cache(maxsize=1)
def _annotation_table() -> pd.DataFrame:
    """root_id -> positions and the label columns shown in the dashboard tooltip."""
    df = pd.read_csv(ANNOTATIONS.path, sep="\t",
                     usecols=["root_id", *POSITIONS.columns, *ATLAS_INFO_COLUMNS])
    df = df.dropna(subset=list(POSITIONS.columns)).drop_duplicates("root_id")
    return df.set_index("root_id")


@dataclass(frozen=True)
class Atlas:
    """All placed annotation neurons; the running brain's placed neurons come first."""

    root_ids: np.ndarray   # int64, atlas order
    xyz_um: np.ndarray     # (n, 3) float, µm
    n_sim: int             # the first n_sim entries are the simulated neurons, in the
                           # same order as `neuron_positions(sim_ids).ids`
    left_x_um: float       # mean x of neurons annotated side == "left"
    right_x_um: float      # mean x of neurons annotated side == "right"


def atlas(sim_ids: Iterable[int]) -> Atlas:
    """Every neuron with a position, simulated ones first (see `Atlas`)."""
    table = _annotation_table()
    sim = neuron_positions(sim_ids).ids
    rest = table.index.to_numpy()[~np.isin(table.index.to_numpy(), sim)]
    order = np.concatenate([sim, rest])
    vox = table.loc[order, list(POSITIONS.columns)].to_numpy(dtype=float)
    xyz = vox * np.asarray(POSITIONS.voxel_um)
    side = table.loc[order, "side"].to_numpy()
    return Atlas(order, xyz, int(sim.size),
                 float(xyz[side == "left", 0].mean()), float(xyz[side == "right", 0].mean()))


def atlas_payload(a: Atlas) -> tuple[dict, bytes]:
    """(JSON header, binary body) for the dashboard.

    The body is little-endian int16 x, y, z per neuron in units of `scale_um`
    (0.1 µm; the FlyWire brain is under 1000 µm across, so int16 is enough).
    """
    q = np.round(a.xyz_um / POSITIONS.atlas_scale_um).astype("<i2")
    header = {
        "units": "um",
        "scale_um": POSITIONS.atlas_scale_um,
        "n": int(a.root_ids.size),
        "n_sim": a.n_sim,
        "left_x_um": round(a.left_x_um, 1),
        "right_x_um": round(a.right_x_um, 1),
        "source": f"{ANNOTATIONS.repo}@{ANNOTATIONS.commit[:7]}:{ANNOTATIONS.repo_path} "
                  f"columns {', '.join(POSITIONS.columns)}; sides from column 'side'",
    }
    return header, q.tobytes()


def atlas_neuron(a: Atlas, index: int) -> dict:
    """Tooltip facts for one atlas entry, straight from the annotation table."""
    rid = int(a.root_ids[index])
    row = _annotation_table().loc[rid]

    def s(col: str) -> str | None:
        v = row[col]
        return None if pd.isna(v) else str(v)

    return {"index": index, "root_id": str(rid), "simulated": index < a.n_sim,
            **{col: s(col) for col in ATLAS_INFO_COLUMNS}}

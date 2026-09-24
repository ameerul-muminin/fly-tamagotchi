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
    df = pd.read_csv(ANNOTATIONS.path, sep="\t", usecols=["root_id", *POSITIONS.columns])
    df = df.dropna(subset=list(POSITIONS.columns)).drop_duplicates("root_id")
    return df.set_index("root_id")


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

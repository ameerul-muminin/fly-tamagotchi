"""Resolve neuron groups from source files and save them to data/neuron_groups.json.

No neuron IDs are typed into this code:
- Sugar GRNs, bitter GRNs and MN9 are parsed from the Shiu et al. `figures.ipynb`
  (pinned commit), i.e. the exact IDs the paper's experiments used.
- Photoreceptors are looked up by `cell_type` in the FlyWire annotation table
  (Schlegel et al. 2024), which uses release-783 root IDs. A root ID names one
  fixed segmentation, so an ID that also appears in the v630 neuron list is the
  same neuron there. Photoreceptors edited between 630 and 783 got new IDs and
  cannot be matched without the CAVE API, so coverage is partial and reported.

Usage: python -m brain.neuron_groups
"""

from __future__ import annotations

import ast
import json
import sys

import pandas as pd

from brain.config import (
    DATA_FILES,
    FLYWIRE_VERSION,
    NEURON_GROUPS_PATH,
    SHIU_COMMIT,
    SHIU_REPO,
    ANNOTATIONS_COMMIT,
    ANNOTATIONS_REPO,
)

PHOTORECEPTOR_TYPES = ("R7", "R8")


def _cell_assignments(source: str) -> dict[str, object]:
    """Return literal top-level assignments (name -> value) in a notebook cell."""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # cells with IPython magics
        return {}
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return out


def _notebook_cells() -> list[dict[str, object]]:
    """Literal assignments of every code cell in the Shiu figures notebook."""
    nb = json.loads(DATA_FILES["figures_notebook"].path.read_text(encoding="utf-8"))
    return [
        _cell_assignments("".join(c["source"])) if c["cell_type"] == "code" else {}
        for c in nb["cells"]
    ]


def _find_cell(cells: list[dict[str, object]], *names: str) -> int:
    """Index of the single cell that assigns all `names`."""
    hits = [i for i, c in enumerate(cells) if all(n in c for n in names)]
    if len(hits) != 1:
        raise ValueError(f"expected one cell assigning {names}, found {hits}")
    return hits[0]


def _source(cell: int, variable: str, note: str = "") -> dict[str, object]:
    return {
        "file": f"github.com/{SHIU_REPO}/blob/{SHIU_COMMIT}/figures.ipynb",
        "cell_index": cell,
        "variable": variable,
        "note": note,
    }


def resolve_shiu_groups() -> dict[str, dict]:
    """Sugar GRNs, bitter GRNs and MN9 as used in Shiu et al. Figure 3A / Figure 2."""
    cells = _notebook_cells()

    # Figure 3A cell: the sugar + bitter experiment, read out at `id_mn9`.
    fig3a = _find_cell(cells, "neu_sugar", "neu_bitter", "id_mn9")
    sugar = list(cells[fig3a]["neu_sugar"])
    bitter = list(cells[fig3a]["neu_bitter"])
    mn9_primary = [cells[fig3a]["id_mn9"]]

    # Every other `neu_sugar` definition in the notebook must agree.
    for i, c in enumerate(cells):
        if "neu_sugar" in c and list(c["neu_sugar"]) != sugar:
            raise ValueError(f"neu_sugar in cell {i} differs from cell {fig3a}")

    # Figure 2 cell lists both MN9 neurons.
    fig2 = _find_cell(cells, "ids_mn9")
    mn9_both = list(cells[fig2]["ids_mn9"])
    if mn9_primary[0] not in mn9_both:
        raise ValueError("id_mn9 is not among ids_mn9")

    return {
        "sugar_grn": {
            "ids": sugar,
            "source": _source(fig3a, "neu_sugar",
                              "Labellar sugar-sensing GRNs, right hemisphere (notebook comment)."),
        },
        "bitter_grn": {
            "ids": bitter,
            "source": _source(fig3a, "neu_bitter", "Bitter GRNs used in Figure 3A."),
        },
        "mn9": {
            "ids": mn9_both,
            "source": _source(fig2, "ids_mn9",
                              "Both MN9 motor neurons; notebook comment says 'left and right'."),
        },
        "mn9_primary": {
            "ids": mn9_primary,
            "source": _source(fig3a, "id_mn9",
                              "The MN9 used for every readout in the paper's notebooks "
                              "(labelled 'left' in Fig 3A; the left/right labels are "
                              "inconsistent between notebook cells)."),
        },
    }


def resolve_photoreceptors(v630_ids: set[int]) -> dict[str, dict]:
    """Photoreceptor groups whose 783 root IDs also exist unchanged in v630."""
    ann = pd.read_csv(
        DATA_FILES["annotations"].path, sep="\t", low_memory=False,
        usecols=["root_id", "super_class", "cell_class", "cell_type", "side"],
    )
    groups: dict[str, dict] = {}
    for ctype in PHOTORECEPTOR_TYPES:
        rows = ann[(ann.super_class == "sensory") & (ann.cell_class == "visual")
                   & (ann.cell_type == ctype)]
        present = rows[rows.root_id.isin(v630_ids)]
        by_side = present.side.value_counts().to_dict()
        groups[f"photoreceptor_{ctype}"] = {
            "ids": sorted(int(x) for x in present.root_id),
            "source": {
                "file": (f"github.com/{ANNOTATIONS_REPO}/blob/{ANNOTATIONS_COMMIT}/"
                         "supplemental_files/Supplemental_file1_neuron_annotations.tsv"),
                "filter": (f"super_class == 'sensory' & cell_class == 'visual' & "
                           f"cell_type == '{ctype}', then root_id present in v630 "
                           "completeness file"),
                "note": (f"Partial coverage: {len(present)} of {len(rows)} annotated "
                         f"(v783) {ctype} have unchanged root IDs in v630. "
                         f"By side: {by_side}. Candidate light input only."),
            },
            # Phase 2 decision: light is a game-only input for now; this group is
            # kept for later and is not wired to any stimulus.
            "partial": True,
            "status": "saved for later; not used as a brain input (light is game-only)",
        }
    return groups


def build_groups() -> dict[str, dict]:
    """Resolve all groups, add counts, and return the full JSON document."""
    v630_ids = set(
        pd.read_csv(DATA_FILES["completeness"].path, index_col=0).index.astype("int64")
    )
    groups = resolve_shiu_groups() | resolve_photoreceptors(v630_ids)
    for name, g in groups.items():
        missing = [i for i in g["ids"] if i not in v630_ids]
        if missing:
            raise ValueError(f"group {name}: {len(missing)} IDs not in v630: {missing[:5]}")
        g["count"] = len(g["ids"])
        g.setdefault("partial", False)
        # FlyWire IDs exceed 2^53, so store as strings for JSON/JS safety.
        g["ids"] = [str(i) for i in g["ids"]]
    return {"flywire_version": FLYWIRE_VERSION, "groups": groups}


def load_groups() -> dict[str, list[int]]:
    """Load data/neuron_groups.json as {group name: [FlyWire root IDs]}."""
    doc = json.loads(NEURON_GROUPS_PATH.read_text(encoding="utf-8"))
    return {name: [int(i) for i in g["ids"]] for name, g in doc["groups"].items()}


def main() -> int:
    doc = build_groups()
    NEURON_GROUPS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    for name, g in doc["groups"].items():
        print(f"{name:22s} {g['count']:5d}  {g['source'].get('note', '')}")
    print(f"Wrote {NEURON_GROUPS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

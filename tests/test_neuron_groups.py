"""Neuron groups: resolved from sources, non-empty, present in the weight matrix."""

import json

from brain.config import NEURON_GROUPS_PATH
from brain.neuron_groups import build_groups, load_groups

REQUIRED = {"sugar_grn", "bitter_grn", "mn9", "mn9_primary"}


def test_required_groups_present_and_nonempty():
    groups = load_groups()
    assert REQUIRED <= groups.keys()
    for name, ids in groups.items():
        assert len(ids) > 0, name
        assert len(set(ids)) == len(ids), f"duplicate IDs in {name}"


def test_every_group_records_count_and_source():
    doc = json.loads(NEURON_GROUPS_PATH.read_text(encoding="utf-8"))
    assert doc["flywire_version"] == 630
    for name, g in doc["groups"].items():
        assert g["count"] == len(g["ids"]), name
        assert g["source"]["file"], name


def test_every_id_exists_in_weight_matrix(connectome):
    index = connectome.index_of()
    w = connectome.weight_matrix(1.0)
    for name, ids in load_groups().items():
        missing = [i for i in ids if i not in index]
        assert not missing, f"{name}: {missing[:5]}"
        # Each neuron takes part in at least one connection.
        idx = [index[i] for i in ids]
        degree = w[idx].getnnz(axis=1) + w[:, idx].getnnz(axis=0)
        assert (degree > 0).all(), name


def test_saved_groups_match_a_fresh_resolution():
    fresh = build_groups()
    saved = json.loads(NEURON_GROUPS_PATH.read_text(encoding="utf-8"))
    assert fresh == saved


def test_sugar_and_bitter_are_disjoint_and_mn9_primary_in_mn9():
    g = load_groups()
    assert not set(g["sugar_grn"]) & set(g["bitter_grn"])
    assert set(g["mn9_primary"]) <= set(g["mn9"])

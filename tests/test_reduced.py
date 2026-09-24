"""Reduced circuit: construction, and Phase 2 validation against the full brain (slow)."""

import json

import numpy as np
import pytest

from brain.config import PHASE2_RESULTS_PATH, REDUCED
from brain.connectome import Connectome
from brain.neuron_groups import load_groups
from brain.reduced import UNREACHED, build_reduced_circuit, hop_distances, subset_connectome


def _toy() -> Connectome:
    # 0 -> 1 -> 2 -> 3, and 4 -> 3, 5 isolated
    pre = np.array([0, 1, 2, 4])
    post = np.array([1, 2, 3, 3])
    return Connectome(ids=np.arange(100, 106), pre=pre, post=post, signed_syn=np.array([5, -3, 2, 7]))


def test_hop_distances_forward_and_reverse():
    c = _toy()
    assert hop_distances(c, np.array([0]), 5).tolist() == [0, 1, 2, 3] + [UNREACHED] * 2
    assert hop_distances(c, np.array([0]), 2).tolist() == [0, 1, 2] + [UNREACHED] * 3
    assert hop_distances(c, np.array([3]), 5, reverse=True).tolist() == [3, 2, 1, 0, 1, UNREACHED]


def test_subset_keeps_exactly_the_internal_connections():
    c = _toy()
    sub = subset_connectome(c, np.array([3, 1, 2]))
    assert sub.ids.tolist() == [101, 102, 103]
    edges = sorted(zip(sub.ids[sub.pre].tolist(), sub.ids[sub.post].tolist(), sub.signed_syn.tolist()))
    assert edges == [(101, 102, -3), (102, 103, 2)]


@pytest.fixture(scope="module")
def circuit(connectome):
    return build_reduced_circuit(connectome)


def test_circuit_contains_every_input_and_output_neuron(circuit):
    ids = set(circuit.connectome.ids.tolist())
    groups = load_groups()
    for name in REDUCED.always_include:
        assert set(groups[name]) <= ids, name


def test_circuit_is_the_path_set(circuit, connectome):
    k = REDUCED.max_path_hops
    total = circuit.d_out.astype(np.int64) + circuit.d_in
    groups = load_groups()
    forced = {i for g in REDUCED.always_include for i in groups[g]}
    ids = circuit.connectome.ids
    off_path = [int(i) for i, t in zip(ids, total) if t > k]
    assert set(off_path) <= forced
    # Every kept neuron's full-brain index maps back to the same ID.
    assert np.array_equal(connectome.ids[circuit.full_index], ids)


def test_circuit_keeps_all_connections_among_kept_neurons(circuit, connectome):
    kept = np.zeros(connectome.n_neurons, dtype=bool)
    kept[circuit.full_index] = True
    inside = kept[connectome.pre] & kept[connectome.post]
    red = circuit.connectome
    assert red.n_edges == int(inside.sum())
    # Same total signed synapses, so weights were carried over unchanged.
    assert red.signed_syn.sum() == connectome.signed_syn[inside].sum()


@pytest.fixture(scope="module")
def report(connectome):
    from brain.validate_reduced import format_report, run_phase2
    rep = run_phase2()
    PHASE2_RESULTS_PATH.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("\n" + format_report(rep))
    return rep


def test_reduced_mn9_within_10_percent_of_full_brain(report):
    for cond in report["phase2_config"]["compared_conditions"]:
        assert report["checks"][f"reduced_matches_full_{cond}"], report["comparison"][cond]


def test_reduced_circuit_reproduces_phase1_effects(report):
    assert report["checks"]["reduced_sugar_drives_mn9"], report["reduced"]["sugar"]
    assert report["checks"]["reduced_bitter_reduces_mn9"], report["reduced"]


def test_shuffled_reduced_circuit_fails(report):
    assert len(report["shuffled_reduced"]) >= 5
    assert report["checks"]["shuffled_reduced_no_sugar_effect_all_shuffles"], report["shuffled_reduced"]
    assert report["checks"]["shuffled_reduced_no_bitter_effect_all_shuffles"], report["shuffled_reduced"]


def test_reduced_circuit_is_fast_enough(report):
    s = report["speed_ms_per_50ms_chunk"]["reduced"]
    assert report["checks"]["speed_mean_under_limit"], s
    assert report["checks"]["speed_p95_under_limit"], s


def test_uses_at_least_five_seeds(report):
    for brain in ("full", "reduced"):
        for r in report[brain].values():
            assert len(r["mn9_rates_hz"]) >= 5

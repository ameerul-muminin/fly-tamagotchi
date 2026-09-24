"""Reduced circuit: the neurons on short paths from the taste inputs to MN9.

The full 127,400-neuron brain is too slow for live play. This keeps every neuron
that lies on a path of at most K connections from a sugar/bitter GRN to an MN9
(see ReducedCircuitConfig and reports/PHASE_2_PLAN.md), with all connections
between kept neurons at their original weights.

Usage: python -m brain.reduced   (prints a summary, writes data/reduced_circuit.json)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from brain.config import REDUCED, REDUCED_CIRCUIT_PATH, ReducedCircuitConfig
from brain.connectome import Connectome, load_connectome
from brain.neuron_groups import load_groups

UNREACHED = np.iinfo(np.int32).max


@dataclass
class ReducedCircuit:
    """A sub-connectome plus how it was built.

    Attributes:
        connectome: the reduced brain (neurons re-indexed 0..n-1).
        full_index: index of each kept neuron in the full connectome.
        d_out, d_in: hops from the source groups / to the target groups, per kept neuron.
        cfg: the settings used.
    """

    connectome: Connectome
    full_index: np.ndarray
    d_out: np.ndarray
    d_in: np.ndarray
    cfg: ReducedCircuitConfig


def hop_distances(conn: Connectome, start: np.ndarray, max_hops: int,
                  reverse: bool = False) -> np.ndarray:
    """Fewest connections from any `start` neuron to each neuron (or to them, if reverse).

    Breadth-first search over all connections, stopping at `max_hops`.
    Neurons not reached get UNREACHED.
    """
    n = conn.n_neurons
    src, dst = (conn.post, conn.pre) if reverse else (conn.pre, conn.post)
    adj = sp.csr_matrix((np.ones(conn.n_edges, dtype=np.int8), (src, dst)), shape=(n, n))
    dist = np.full(n, UNREACHED, dtype=np.int32)
    front = np.unique(np.asarray(start, dtype=np.int64))
    dist[front] = 0
    for h in range(1, max_hops + 1):
        if front.size == 0:
            break
        nxt = np.unique(adj[front].indices)
        nxt = nxt[dist[nxt] == UNREACHED]
        dist[nxt] = h
        front = nxt
    return dist


def subset_connectome(conn: Connectome, keep: np.ndarray) -> Connectome:
    """Neurons `keep` (full-brain indices, sorted) and every connection among them."""
    keep = np.sort(np.asarray(keep, dtype=np.int64))
    new_index = np.full(conn.n_neurons, -1, dtype=np.int64)
    new_index[keep] = np.arange(keep.size)
    both = (new_index[conn.pre] >= 0) & (new_index[conn.post] >= 0)
    return Connectome(
        ids=conn.ids[keep],
        pre=new_index[conn.pre[both]],
        post=new_index[conn.post[both]],
        signed_syn=conn.signed_syn[both],
    )


def build_reduced_circuit(conn: Connectome,
                          cfg: ReducedCircuitConfig = REDUCED) -> ReducedCircuit:
    """Select the reduced circuit from the full connectome."""
    index = conn.index_of()
    groups = load_groups()

    def idx(names: tuple[str, ...]) -> np.ndarray:
        return np.array([index[i] for g in names for i in groups[g]], dtype=np.int64)

    k = cfg.max_path_hops
    d_out = hop_distances(conn, idx(cfg.source_groups), k)
    d_in = hop_distances(conn, idx(cfg.target_groups), k, reverse=True)
    on_path = (d_out.astype(np.int64) + d_in) <= k
    on_path[idx(cfg.always_include)] = True
    keep = np.flatnonzero(on_path)
    return ReducedCircuit(subset_connectome(conn, keep), keep, d_out[keep], d_in[keep], cfg)


def summary(rc: ReducedCircuit, full: Connectome) -> dict:
    """Sizes and hop histograms, for reports and data/reduced_circuit.json."""
    c = rc.connectome
    finite = lambda d: d[d != UNREACHED]  # noqa: E731
    return {
        "definition": (f"neurons with d_out + d_in <= {rc.cfg.max_path_hops}, "
                       f"d_out = hops from {list(rc.cfg.source_groups)}, "
                       f"d_in = hops to {list(rc.cfg.target_groups)}, all connections; "
                       f"plus {list(rc.cfg.always_include)}"),
        "n_neurons": c.n_neurons,
        "n_edges": c.n_edges,
        "fraction_of_full_neurons": c.n_neurons / full.n_neurons,
        "fraction_of_full_edges": c.n_edges / full.n_edges,
        "d_out_histogram": np.bincount(finite(rc.d_out)).tolist(),
        "d_in_histogram": np.bincount(finite(rc.d_in)).tolist(),
    }


def main() -> int:
    full = load_connectome()
    rc = build_reduced_circuit(full)
    doc = summary(rc, full)
    for k, v in doc.items():
        print(f"{k:26s} {v}")
    doc["ids"] = [str(i) for i in rc.connectome.ids]
    REDUCED_CIRCUIT_PATH.write_text(json.dumps(doc), encoding="utf-8")
    print(f"Wrote {REDUCED_CIRCUIT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

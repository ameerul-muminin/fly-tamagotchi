"""Load the FlyWire connectome and build signed sparse weight matrices."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp

from brain.config import DATA_FILES


@dataclass
class Connectome:
    """Neurons and signed connections of the brain.

    Attributes:
        ids: FlyWire root ID of each neuron; position = matrix index.
        pre, post: matrix indices of each connection.
        signed_syn: synapse count x sign (+1 excitatory, -1 inhibitory), as in the
            repo's `Excitatory x Connectivity` column.
    """

    ids: np.ndarray
    pre: np.ndarray
    post: np.ndarray
    signed_syn: np.ndarray

    @property
    def n_neurons(self) -> int:
        return len(self.ids)

    @property
    def n_edges(self) -> int:
        return len(self.pre)

    def index_of(self) -> dict[int, int]:
        """Map FlyWire root ID -> matrix index."""
        return {int(f): i for i, f in enumerate(self.ids)}

    def weight_matrix(self, w_syn: float) -> sp.csr_matrix:
        """Signed weights in mV, shape (pre, post), CSR.

        Rows are presynaptic so that the outgoing weights of a spiking neuron
        are one contiguous row slice. Weight = signed synapse count x w_syn,
        matching model.py (`syn.w = Excitatory x Connectivity * w_syn`).
        """
        n = self.n_neurons
        w = self.signed_syn.astype(np.float64) * w_syn
        return sp.csr_matrix((w, (self.pre, self.post)), shape=(n, n))


def load_connectome() -> Connectome:
    """Load the v630 completeness + connectivity files from data/."""
    comp = pd.read_csv(DATA_FILES["completeness"].path, index_col=0)
    con = pd.read_parquet(
        DATA_FILES["connectivity"].path,
        columns=["Presynaptic_Index", "Postsynaptic_Index", "Excitatory x Connectivity"],
    )
    return Connectome(
        ids=comp.index.to_numpy(dtype=np.int64),
        pre=con["Presynaptic_Index"].to_numpy(dtype=np.int64),
        post=con["Postsynaptic_Index"].to_numpy(dtype=np.int64),
        signed_syn=con["Excitatory x Connectivity"].to_numpy(dtype=np.int64),
    )


def shuffle_connectome(conn: Connectome, seed: int) -> Connectome:
    """Return a control brain with every connection's target randomized.

    Keeps the same neurons, the same number of connections, each connection's
    presynaptic neuron and weight (so the weight distribution and each neuron's
    out-degree are unchanged). Only the postsynaptic target is redrawn uniformly,
    rejecting self-connections and duplicate (pre, post) pairs.
    """
    rng = np.random.default_rng(seed)
    n = conn.n_neurons
    pre = conn.pre.copy()
    post = rng.integers(0, n, size=len(pre))
    bad = _invalid_edges(pre, post, n)
    while bad.any():
        post[bad] = rng.integers(0, n, size=int(bad.sum()))
        bad = _invalid_edges(pre, post, n)
    return Connectome(ids=conn.ids, pre=pre, post=post, signed_syn=conn.signed_syn.copy())


def _invalid_edges(pre: np.ndarray, post: np.ndarray, n: int) -> np.ndarray:
    """Mask of self-connections and all-but-first copies of duplicate pairs."""
    bad = pre == post
    key = pre * n + post
    _, first = np.unique(key, return_index=True)
    dup = np.ones(len(key), dtype=bool)
    dup[first] = False
    return bad | dup

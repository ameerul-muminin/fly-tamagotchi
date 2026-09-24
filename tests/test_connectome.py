"""Weight matrix construction and the shuffled-brain control."""

import numpy as np
import pandas as pd

from brain.config import DATA_FILES, LIFParams


def test_matrix_matches_parquet(connectome):
    raw = pd.read_parquet(DATA_FILES["connectivity"].path)
    w_syn = LIFParams().w_syn
    w = connectome.weight_matrix(w_syn)
    assert w.shape == (connectome.n_neurons, connectome.n_neurons) == (127_400, 127_400)
    assert w.nnz == len(raw) == 14_687_178

    # Indices in the parquet agree with the completeness file's row order.
    assert np.array_equal(connectome.ids[raw["Presynaptic_Index"]], raw["Presynaptic_ID"])
    assert np.array_equal(connectome.ids[raw["Postsynaptic_Index"]], raw["Postsynaptic_ID"])

    # Weight = synapse count x sign x w_syn, sign taken from the `Excitatory` column.
    got = np.asarray(w[raw["Presynaptic_Index"].to_numpy(), raw["Postsynaptic_Index"].to_numpy()]).ravel()
    expected = raw["Connectivity"].to_numpy() * raw["Excitatory"].to_numpy() * w_syn
    assert np.allclose(got, expected)
    assert set(np.unique(raw["Excitatory"])) == {-1, 1}


def test_shuffle_preserves_counts_and_weights(connectome, shuffled):
    n = connectome.n_neurons
    assert shuffled.n_neurons == n and np.array_equal(shuffled.ids, connectome.ids)
    assert shuffled.n_edges == connectome.n_edges
    # Same source neuron and weight for every connection -> same out-degrees
    # and identical weight distribution.
    assert np.array_equal(shuffled.pre, connectome.pre)
    assert np.array_equal(shuffled.signed_syn, connectome.signed_syn)
    # Valid graph: no self-connections, no duplicate pairs.
    assert not np.any(shuffled.pre == shuffled.post)
    assert np.unique(shuffled.pre * n + shuffled.post).size == shuffled.n_edges
    # Targets really are randomized.
    assert np.mean(shuffled.post == connectome.post) < 0.001


def test_shuffle_is_deterministic_per_seed(connectome):
    from brain.connectome import shuffle_connectome
    small = type(connectome)(connectome.ids, connectome.pre[:10_000], connectome.post[:10_000],
                             connectome.signed_syn[:10_000])
    a, b = shuffle_connectome(small, 1), shuffle_connectome(small, 1)
    c = shuffle_connectome(small, 2)
    assert np.array_equal(a.post, b.post) and not np.array_equal(a.post, c.post)

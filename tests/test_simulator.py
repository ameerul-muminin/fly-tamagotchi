"""Unit tests of the LIF simulator on small synthetic networks."""

from pathlib import Path

import numpy as np
import pytest
import scipy.sparse as sp

from brain.config import LIFParams
from brain.simulator import LIFSimulator

P = LIFParams()


def chain(weights_mv: dict[tuple[int, int], float], n: int) -> sp.csr_matrix:
    """Weight matrix (pre, post) from {(pre, post): mV}."""
    if not weights_mv:
        return sp.csr_matrix((n, n))
    (pre, post), w = zip(*weights_mv.keys()), list(weights_mv.values())
    return sp.csr_matrix((w, (pre, post)), shape=(n, n))


def test_no_input_stays_at_rest():
    sim = LIFSimulator(chain({(0, 1): 5.0}, 3), P)
    res = sim.run(200)
    assert res.neurons.size == 0
    assert np.allclose(sim.v, P.v_0) and np.allclose(sim.g, 0)


def test_exact_integration_matches_analytic_solution():
    sim = LIFSimulator(chain({}, 1), P)
    g0 = 3.0
    sim.g[0] = g0
    sim.run(10.0)
    t = 10.0
    expected_g = g0 * np.exp(-t / P.tau)
    expected_v = P.v_0 + g0 * P.tau / (P.tau - P.t_mbr) * (np.exp(-t / P.tau) - np.exp(-t / P.t_mbr))
    assert sim.g[0] == pytest.approx(expected_g, rel=1e-9)
    assert sim.v[0] == pytest.approx(expected_v, rel=1e-9)


def test_spike_arrives_after_synaptic_delay():
    w = 2.0
    sim = LIFSimulator(chain({(0, 1): w}, 2), P)
    delay_steps = round(P.t_dly / P.dt)
    sim.v[0] = 0.0  # above threshold: neuron 0 spikes at step 0
    first = sim.run(P.dt)
    assert first.neurons.tolist() == [0]
    sim.run(P.dt * (delay_steps - 1))  # steps 1 .. delay-1
    assert sim.g[1] == 0.0
    sim.run(P.dt)  # step `delay`: g += w
    assert sim.g[1] == pytest.approx(w)


def test_refractory_period_limits_interspike_interval():
    # Neuron 0: Poisson-driven at 5 kHz, drives neuron 1 very strongly.
    sim = LIFSimulator(chain({(0, 1): 1000.0}, 2), P, seed=1)
    sim.set_input("drive", np.array([0]), 5000.0)
    res = sim.run(300)
    t1 = res.times_ms[res.neurons == 1]
    isi_steps = np.round(np.diff(t1) / P.dt).astype(int)
    assert t1.size > 50
    # Brian2: frozen for steps n+1 .. n+21 after a spike at step n, so ISI >= 22 steps;
    # the neuron is driven hard enough to fire soon after refractoriness ends.
    rfc_steps = round(P.t_rfc / P.dt)
    assert rfc_steps <= isi_steps.min() <= rfc_steps + 10


def test_poisson_targets_have_no_refractory_period():
    sim = LIFSimulator(chain({}, 1), P, seed=0)
    sim.set_input("drive", np.array([0]), 1e4)  # an input event every step
    res = sim.run(20)
    # An event at step k spikes at k+1; the event added at k+1 is lost to reset,
    # so the neuron fires every second step.
    assert np.all(np.round(np.diff(res.times_ms) / P.dt) == 2)


def test_poisson_rate_matches_requested_rate():
    sim = LIFSimulator(chain({}, 50), P, seed=3)
    sim.set_input("drive", np.arange(50), 100.0)
    rate = sim.run(2000).counts(50).mean() / 2.0
    assert 95 <= rate <= 101


def test_chunked_run_equals_single_run():
    rng = np.random.default_rng(0)
    n = 300
    w = sp.random(n, n, density=0.05, random_state=1, format="csr") * 20.0
    w.data *= rng.choice([-1.0, 1.0], size=w.nnz)

    def simulate(chunks):
        sim = LIFSimulator(w, P, seed=7)
        sim.set_input("drive", np.arange(20), 150.0)
        out = [sim.run(c) for c in chunks]
        return np.concatenate([r.neurons for r in out]), np.concatenate([r.times_ms for r in out])

    n1, t1 = simulate([100.0])
    n2, t2 = simulate([50.0, 50.0])
    assert n1.size > 0
    assert np.array_equal(n1, n2) and np.allclose(t1, t2)


def test_synaptic_input_to_refractory_neuron_is_discarded():
    # Brian2 conditional write: g of a refractory neuron ignores incoming spikes.
    sim = LIFSimulator(chain({(0, 1): 2.0}, 2), P)
    delay = round(P.t_dly / P.dt)
    sim.v[1] = 0.0          # neuron 1 spikes at step 0 -> refractory steps 1..21
    sim.v[0] = 0.0          # neuron 0 spikes at step 0 -> arrives at step 18
    sim.run(P.dt * (delay + 1))
    assert sim.g[1] == 0.0


def test_matches_brian2_reference_spike_for_spike():
    """Same spikes as Shiu et al. model.run_trial under Brian2 (fixture from
    tests/fixtures/make_brian2_fixture.py, deterministic 10 kHz input)."""
    fx = np.load(Path(__file__).parent / "fixtures" / "brian2_tiny_network.npz")
    n = 300
    w = sp.csr_matrix((fx["signed_syn"] * P.w_syn, (fx["pre"], fx["post"])), shape=(n, n))
    sim = LIFSimulator(w, P)
    sim.set_input("drive", np.arange(int(fx["n_inputs"])), 1e4)
    res = sim.run(float(fx["t_ms"]))
    ours = sorted(zip(np.round(res.times_ms / P.dt).astype(int).tolist(), res.neurons.tolist()))
    brian = list(zip(fx["spike_steps"].tolist(), fx["spike_neurons"].tolist()))
    assert len(brian) > 10_000
    assert ours == brian


def test_reset_state_returns_to_rest_but_keeps_inputs():
    sim = LIFSimulator(chain({}, 2), P, seed=0)
    sim.set_input("drive", np.array([0]), 200.0)
    sim.run(50)
    sim.reset_state()
    assert sim.t_ms == 0 and np.allclose(sim.v, P.v_0)
    assert sim.run(200).neurons.size > 0

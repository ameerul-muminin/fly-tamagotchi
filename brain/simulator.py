"""Chunked leaky integrate-and-fire simulator (Shiu et al. 2024 model in NumPy/SciPy).

Each time step follows Brian2's default schedule, which the reference model runs on:
    1. groups:     integrate v, g exactly (skipped for refractory neurons)
    2. thresholds: spike if v > v_th and not refractory
    3. synapses:   deliver spikes emitted t_dly ago (g_post += w);
                   Poisson inputs add w_syn * f_poi straight to v;
                   both are discarded for refractory neurons (Brian2 conditional write)
    4. resets:     v = v_rst, g = 0 for neurons that spiked this step
Checked spike-for-spike against the repo's own `model.run_trial` under Brian2
on a small network with deterministic input (see tests/test_simulator.py).
State persists between `run` calls, so the brain can be advanced in 50 ms chunks.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from brain.config import LIFParams


@dataclass
class ChunkResult:
    """Spikes produced by one `run` call.

    Attributes:
        t_start_ms: simulated time at the start of the chunk.
        duration_ms: length of the chunk.
        neurons: matrix index of each spike.
        times_ms: absolute time of each spike.
    """

    t_start_ms: float
    duration_ms: float
    neurons: np.ndarray
    times_ms: np.ndarray

    def counts(self, n_neurons: int) -> np.ndarray:
        """Spike count per neuron in this chunk."""
        return np.bincount(self.neurons, minlength=n_neurons)


class LIFSimulator:
    """Leaky integrate-and-fire network driven by Poisson inputs.

    Args:
        weights: signed weights in mV, shape (pre, post), e.g. from
            `Connectome.weight_matrix(params.w_syn)`.
        params: LIF constants.
        seed: seed for the Poisson input random stream.
    """

    def __init__(self, weights: sp.csr_matrix, params: LIFParams, seed: int = 0) -> None:
        if weights.shape[0] != weights.shape[1]:
            raise ValueError("weight matrix must be square")
        self.p = params
        self.n = weights.shape[0]
        self._w = weights.tocsr()
        self._rng = np.random.default_rng(seed)

        dt = params.dt
        # Exact solution of the linear system over one step (Brian2 method='linear').
        self._decay_v = np.exp(-dt / params.t_mbr)
        self._decay_g = np.exp(-dt / params.tau)
        self._g_to_v = params.tau / (params.tau - params.t_mbr) * (self._decay_g - self._decay_v)

        self._delay_steps = int(round(params.t_dly / dt))
        # Brian2: not_refractory = timestep(t - lastspike) >= timestep(t_rfc), so after a
        # spike at step n the neuron is frozen for steps n+1 .. n+rfc_steps-1.
        self._frozen_steps = max(int(round(params.t_rfc / dt)) - 1, 0)
        if self._delay_steps < 1:
            raise ValueError("synaptic delay must be at least one time step")
        self._poisson_jump = params.w_syn * params.f_poi

        # Neurons that receive Poisson input get no refractory period (model.py `poi`).
        self._has_rfc = np.ones(self.n, dtype=bool)
        self._inputs: dict[str, tuple[np.ndarray, float]] = {}
        self.reset_state()

    # ------------------------------------------------------------------ state
    def reset_state(self) -> None:
        """Put every neuron at rest and clear pending spikes. Inputs are kept."""
        self.v = np.full(self.n, self.p.v_0, dtype=np.float64)
        self.g = np.zeros(self.n, dtype=np.float64)
        self.step = 0
        empty = np.empty(0, dtype=np.int64)
        # Spikes in flight: slot k % delay holds spikes emitted at step k - delay.
        self._in_flight = [empty] * self._delay_steps
        # Spikes of the last `frozen_steps` steps (those neurons are refractory).
        self._recent = deque([empty] * self._frozen_steps, maxlen=max(self._frozen_steps, 1))

    @property
    def t_ms(self) -> float:
        """Current simulated time in ms."""
        return self.step * self.p.dt

    # ----------------------------------------------------------------- inputs
    def set_input(self, name: str, indices: np.ndarray, rate_hz: float) -> None:
        """Drive neurons `indices` with independent Poisson spike input at `rate_hz`.

        Registering a group removes the refractory period of its neurons, as the
        reference does for all Poisson targets; this stays in effect if the
        rate is later set to 0.
        """
        idx = np.asarray(indices, dtype=np.int64)
        if rate_hz < 0:
            raise ValueError("rate must be non-negative")
        self._inputs[name] = (idx, float(rate_hz))
        self._has_rfc[idx] = False

    def set_rate(self, name: str, rate_hz: float) -> None:
        """Change the rate of an already registered input group."""
        idx, _ = self._inputs[name]
        self.set_input(name, idx, rate_hz)

    # -------------------------------------------------------------------- run
    def run(self, duration_ms: float) -> ChunkResult:
        """Advance the simulation by `duration_ms` and return the spikes."""
        n_steps = int(round(duration_ms / self.p.dt))
        t0 = self.t_ms
        spk_neurons: list[np.ndarray] = []
        spk_steps: list[np.ndarray] = []
        for _ in range(n_steps):
            spiked = self._advance()
            if spiked.size:
                spk_neurons.append(spiked)
                spk_steps.append(np.full(spiked.size, self.step - 1, dtype=np.int64))
        neurons = np.concatenate(spk_neurons) if spk_neurons else np.empty(0, np.int64)
        steps = np.concatenate(spk_steps) if spk_steps else np.empty(0, np.int64)
        return ChunkResult(t0, n_steps * self.p.dt, neurons, steps * self.p.dt)

    def _advance(self) -> np.ndarray:
        """One time step; returns indices of neurons that spiked."""
        p = self.p
        v, g = self.v, self.g

        # 1. integrate; refractory neurons are frozen (equations 'unless refractory')
        refr = self._refractory_indices()
        v_keep, g_keep = v[refr], g[refr]
        v -= p.v_0
        v *= self._decay_v
        v += self._g_to_v * g
        v += p.v_0
        g *= self._decay_g
        v[refr] = v_keep
        g[refr] = g_keep

        # 2. threshold: v > v_th and not refractory
        spiked = np.flatnonzero(v > p.v_th)
        if refr.size and spiked.size:
            spiked = spiked[~np.isin(spiked, refr)]

        # 3a. deliver spikes emitted `delay` steps ago
        slot = self.step % self._delay_steps
        arriving = self._in_flight[slot]
        if arriving.size:
            rows = self._w[arriving]
            np.add.at(g, rows.indices, rows.data)
        self._in_flight[slot] = spiked

        # 3b. Poisson input: N=1 source per neuron, each event adds w_syn * f_poi to v
        for idx, rate in self._inputs.values():
            if rate > 0 and idx.size:
                hits = idx[self._rng.random(idx.size) < rate * 1e-3 * p.dt]
                v[hits] += self._poisson_jump

        # 3c. Brian2 gives '(unless refractory)' variables a conditional write on
        #     not_refractory, so synaptic/Poisson writes to refractory neurons are
        #     discarded (neurons that spiked this step are reset below anyway).
        v[refr] = v_keep
        g[refr] = g_keep

        # 4. reset
        v[spiked] = p.v_rst
        g[spiked] = 0.0
        if self._frozen_steps:
            self._recent.append(spiked[self._has_rfc[spiked]])
        self.step += 1
        return spiked

    def _refractory_indices(self) -> np.ndarray:
        """Neurons that spiked within the last `frozen_steps` steps (and have a rfc)."""
        if self._frozen_steps == 0:
            return np.empty(0, dtype=np.int64)
        parts = [a for a in self._recent if a.size]
        return np.concatenate(parts) if parts else np.empty(0, dtype=np.int64)

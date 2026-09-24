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

Speed notes (Phase 2): the Poisson draws for a whole chunk are made in one call.
NumPy's generator stream does not depend on how draws are split, so this gives the
same numbers, in the same order, as one draw per input per step.
Optional background noise (off by default) uses its own random stream, so turning
it on never changes the Poisson input spikes.

Two backends run the same step: "numpy" (`_advance` below, checked against Brian2)
and "numba" (brain/lif_kernel.py, one compiled call per chunk, checked to give the
same spikes as "numpy"). "auto" uses numba when it is installed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp

from brain.config import LIFParams, NoiseParams

try:
    from brain.lif_kernel import run_chunk as _numba_run_chunk
except ImportError:  # numba not installed
    _numba_run_chunk = None

BACKENDS = ("auto", "numpy", "numba")
_NEVER = np.iinfo(np.int64).min // 2  # "last spike step" of a neuron that never spiked


def default_backend() -> str:
    """Backend that "auto" resolves to: numba if installed, else numpy."""
    return "numpy" if _numba_run_chunk is None else "numba"


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
        noise: optional background noise for live play (None = no noise, as in
            the reference model and all validation runs).
        backend: "numpy", "numba" or "auto" (numba if installed).
    """

    def __init__(self, weights: sp.csr_matrix, params: LIFParams, seed: int = 0,
                 noise: NoiseParams | None = None, backend: str = "auto") -> None:
        if weights.shape[0] != weights.shape[1]:
            raise ValueError("weight matrix must be square")
        if backend not in BACKENDS:
            raise ValueError(f"backend must be one of {BACKENDS}")
        if backend == "numba" and _numba_run_chunk is None:
            raise ImportError("backend 'numba' requested but numba is not installed")
        if backend == "auto":
            backend = default_backend()
        self.backend = backend
        self.p = params
        self.n = weights.shape[0]
        w = weights.tocsr(copy=True)
        w.sum_duplicates()
        self._indptr = w.indptr.astype(np.int64)
        self._indices = w.indices.astype(np.int64)
        self._data = w.data.astype(np.float64)
        self._rng = np.random.default_rng(seed)
        self._noise_rng = np.random.default_rng([seed, 0x6E6F697A])
        self.noise = noise

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
        if self.backend == "numba":
            # Step of each neuron's last spike (refractory while step - last <= frozen),
            # and a ring buffer of spikes in flight (slot k % delay: emitted at k - delay).
            self._last_spike = np.full(self.n, _NEVER, dtype=np.int64)
            self._slot_buf = np.zeros((self._delay_steps, self.n), dtype=np.int64)
            self._slot_len = np.zeros(self._delay_steps, dtype=np.int64)
            return
        # Spikes in flight: slot k % delay holds spikes emitted at step k - delay.
        self._in_flight = [empty] * self._delay_steps
        # Spikes of the last `frozen_steps` steps (those neurons are refractory), and
        # their concatenation in time order, so the oldest step drops off the front.
        self._recent = deque([empty] * self._frozen_steps, maxlen=max(self._frozen_steps, 1))
        self._refr = empty
        self._refr_mask = np.zeros(self.n, dtype=bool)

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

    def rate(self, name: str) -> float:
        """Current rate of a registered input group [Hz]."""
        return self._inputs[name][1]

    # -------------------------------------------------------------------- run
    def run(self, duration_ms: float) -> ChunkResult:
        """Advance the simulation by `duration_ms` and return the spikes."""
        n_steps = int(round(duration_ms / self.p.dt))
        t0 = self.t_ms
        poi_targets, poi_hits = self._draw_poisson(n_steps)
        noise_targets, noise_bounds = self._draw_noise(n_steps)
        if self.backend == "numba":
            neurons, steps = self._run_numba(n_steps, poi_targets, poi_hits,
                                             noise_targets, noise_bounds)
        else:
            spk_neurons: list[np.ndarray] = []
            spk_steps: list[np.ndarray] = []
            for s in range(n_steps):
                spiked = self._advance(poi_targets[poi_hits[s]],
                                       noise_targets[noise_bounds[s]:noise_bounds[s + 1]])
                if spiked.size:
                    spk_neurons.append(spiked)
                    spk_steps.append(np.full(spiked.size, self.step - 1, dtype=np.int64))
            neurons = np.concatenate(spk_neurons) if spk_neurons else np.empty(0, np.int64)
            steps = np.concatenate(spk_steps) if spk_steps else np.empty(0, np.int64)
        return ChunkResult(t0, n_steps * self.p.dt, neurons, steps * self.p.dt)

    def _draw_poisson(self, n_steps: int) -> tuple[np.ndarray, np.ndarray]:
        """Poisson targets and a (n_steps, n_targets) mask of which are hit per step.

        Draws in the same order as one `rng.random(idx.size)` call per active input
        per step, so the stream is identical to drawing step by step.
        """
        active = [(idx, rate) for idx, rate in self._inputs.values() if rate > 0 and idx.size]
        if not active:
            return np.empty(0, np.int64), np.zeros((n_steps, 0), dtype=bool)
        targets = np.concatenate([idx for idx, _ in active])
        prob = np.concatenate([np.full(idx.size, rate * 1e-3 * self.p.dt) for idx, rate in active])
        return targets, self._rng.random((n_steps, targets.size)) < prob

    def _draw_noise(self, n_steps: int) -> tuple[np.ndarray, np.ndarray]:
        """Noise targets and bounds: step s hits targets[bounds[s]:bounds[s + 1]].

        Uses its own random stream, so noise never changes the Poisson input.
        """
        nz = self.noise
        if nz is None or nz.rate_hz <= 0 or nz.jump_mv == 0:
            return np.empty(0, np.int64), np.zeros(n_steps + 1, dtype=np.int64)
        per_step = self._noise_rng.binomial(self.n, nz.rate_hz * 1e-3 * self.p.dt, size=n_steps)
        targets = self._noise_rng.integers(0, self.n, size=int(per_step.sum()))
        return targets, np.concatenate([[0], np.cumsum(per_step)]).astype(np.int64)

    def _run_numba(self, n_steps: int, poi_targets: np.ndarray, poi_hits: np.ndarray,
                   noise_targets: np.ndarray, noise_bounds: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray]:
        """Run a chunk with the compiled kernel; returns (neurons, steps) of spikes."""
        p = self.p
        neurons, steps = _numba_run_chunk(
            self.v, self.g, self._last_spike, self._has_rfc, self._slot_buf, self._slot_len,
            self.step, n_steps, self._indptr, self._indices, self._data,
            poi_targets.astype(np.int64), np.ascontiguousarray(poi_hits), self._poisson_jump,
            noise_targets.astype(np.int64), noise_bounds,
            0.0 if self.noise is None else float(self.noise.jump_mv),
            p.v_0, p.v_rst, p.v_th, self._decay_v, self._decay_g, self._g_to_v,
            self._delay_steps, self._frozen_steps,
        )
        self.step += n_steps
        return neurons, steps

    def _advance(self, poisson_hits: np.ndarray, noise_hits: np.ndarray) -> np.ndarray:
        """One time step (numpy backend); returns indices of neurons that spiked."""
        p = self.p
        v, g = self.v, self.g

        # 1. integrate; refractory neurons are frozen (equations 'unless refractory')
        refr = self._refr
        v_keep, g_keep = v[refr], g[refr]
        v -= p.v_0
        v *= self._decay_v
        v += self._g_to_v * g
        v += p.v_0
        g *= self._decay_g
        if refr.size:
            v[refr] = v_keep
            g[refr] = g_keep

        # 2. threshold: v > v_th and not refractory
        spiked = np.flatnonzero(v > p.v_th)
        if refr.size and spiked.size:
            spiked = spiked[~self._refr_mask[spiked]]

        # 3a. deliver spikes emitted `delay` steps ago: g_post += w for each outgoing
        #     connection, read straight from the CSR arrays (rows = presynaptic).
        slot = self.step % self._delay_steps
        arriving = self._in_flight[slot]
        if arriving.size == 1:
            lo, hi = self._indptr[arriving[0]], self._indptr[arriving[0] + 1]
            g[self._indices[lo:hi]] += self._data[lo:hi]  # no repeated column within a row
        elif arriving.size:
            starts = self._indptr[arriving]
            lens = self._indptr[arriving + 1] - starts
            ends = np.cumsum(lens)
            pos = np.arange(ends[-1]) + np.repeat(starts - (ends - lens), lens)
            np.add.at(g, self._indices[pos], self._data[pos])
        self._in_flight[slot] = spiked

        # 3b. Poisson input: N=1 source per neuron, each event adds w_syn * f_poi to v
        if poisson_hits.size:
            np.add.at(v, poisson_hits, self._poisson_jump)
        # 3b'. optional background noise: the same kind of write, not in the reference
        if noise_hits.size:
            np.add.at(v, noise_hits, self.noise.jump_mv)

        # 3c. Brian2 gives '(unless refractory)' variables a conditional write on
        #     not_refractory, so synaptic/Poisson writes to refractory neurons are
        #     discarded (neurons that spiked this step are reset below anyway).
        if refr.size:
            v[refr] = v_keep
            g[refr] = g_keep

        # 4. reset
        v[spiked] = p.v_rst
        g[spiked] = 0.0
        if self._frozen_steps:
            new = spiked[self._has_rfc[spiked]]
            oldest = self._recent[0]
            self._recent.append(new)
            self._refr = np.concatenate([self._refr[oldest.size:], new])
            self._refr_mask[oldest] = False
            self._refr_mask[new] = True
        self.step += 1
        return spiked

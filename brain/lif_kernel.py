"""Compiled (numba) version of one simulator chunk.

Does exactly what `LIFSimulator._advance` does, step by step, with the same
floating-point operations in the same order, so both backends produce identical
spikes (checked in tests/test_simulator.py). Refractoriness is stored as the step
of each neuron's last spike instead of a list of recent spikes.
"""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def _grow(a: np.ndarray) -> np.ndarray:
    out = np.empty(a.size * 2, dtype=a.dtype)
    out[:a.size] = a
    return out


@njit(cache=True, nogil=True)  # nogil: the server runs chunks in a worker thread
def run_chunk(
    v, g, last_spike, has_rfc, slot_buf, slot_len, step0, n_steps,
    indptr, indices, data,
    poi_targets, poi_hits, poi_jump,
    noise_targets, noise_bounds, noise_jump,
    v_0, v_rst, v_th, decay_v, decay_g, g_to_v, delay, frozen,
):
    """Advance `n_steps` steps from step `step0`, updating the state arrays in place.

    Args:
        v, g: membrane potential and synaptic conductance per neuron.
        last_spike: step of the last spike of each neuron that has a refractory
            period (very negative if none); a neuron is frozen while
            step - last_spike <= frozen.
        has_rfc: False for Poisson-input neurons (no refractory period).
        slot_buf, slot_len: ring buffer of spikes in flight; slot k % delay holds
            the spikes emitted at step k - delay.
        indptr, indices, data: CSR weights, rows = presynaptic.
        poi_targets, poi_hits: Poisson targets and a (n_steps, len(targets)) hit mask.
        noise_targets, noise_bounds: noise targets of step s are
            noise_targets[noise_bounds[s]:noise_bounds[s + 1]].

    Returns:
        (neuron index, step) of every spike, in step order and ascending index.
    """
    n = v.size
    cap = 1024
    out_n = np.empty(cap, dtype=np.int64)
    out_s = np.empty(cap, dtype=np.int64)
    cnt = 0
    spk = np.empty(n, dtype=np.int64)
    for s in range(n_steps):
        m = step0 + s
        # 1. integrate; refractory neurons keep their values. Written as a select
        #    without branches so the compiler can vectorize it.
        for i in range(n):
            frz = m - last_spike[i] <= frozen
            vi = v[i]
            gi = g[i]
            vn = vi - v_0
            vn = vn * decay_v
            vn = vn + g_to_v * gi
            vn = vn + v_0
            v[i] = vi if frz else vn
            g[i] = gi if frz else gi * decay_g
        # 2. threshold: v > v_th and not refractory
        ns = 0
        for i in range(n):
            if v[i] > v_th and m - last_spike[i] > frozen:
                spk[ns] = i
                ns += 1
        # 3a. deliver spikes emitted `delay` steps ago; writes to refractory
        #     neurons are discarded (Brian2 conditional write)
        slot = m % delay
        for a in range(slot_len[slot]):
            pre = slot_buf[slot, a]
            for k in range(indptr[pre], indptr[pre + 1]):
                post = indices[k]
                if m - last_spike[post] > frozen:
                    g[post] += data[k]
        for a in range(ns):
            slot_buf[slot, a] = spk[a]
        slot_len[slot] = ns
        # 3b. Poisson input and optional noise, added straight to v
        for j in range(poi_targets.size):
            if poi_hits[s, j]:
                t = poi_targets[j]
                if m - last_spike[t] > frozen:
                    v[t] += poi_jump
        for k in range(noise_bounds[s], noise_bounds[s + 1]):
            t = noise_targets[k]
            if m - last_spike[t] > frozen:
                v[t] += noise_jump
        # 4. reset
        for a in range(ns):
            i = spk[a]
            v[i] = v_rst
            g[i] = 0.0
            if has_rfc[i]:
                last_spike[i] = m
            if cnt == cap:
                out_n = _grow(out_n)
                out_s = _grow(out_s)
                cap *= 2
            out_n[cnt] = i
            out_s[cnt] = m
            cnt += 1
    return out_n[:cnt].copy(), out_s[:cnt].copy()

"""The live brain: applies phone events as input rates and summarises spikes.

Threading model: `run_chunk` is the only method that touches the simulator from a
worker thread. Everything else (events, rate changes, summaries) runs on the
asyncio event-loop thread, and rates change only between chunks.

Nothing here decides behavior. `eating` is a readout of MN9 spikes, and bitter
reaches MN9 only through the simulated connectome.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp

from brain.config import LIFParams
from brain.simulator import ChunkResult, LIFSimulator
from server.config import ServerConfig


class EventError(ValueError):
    """A phone message that cannot be applied; the text is sent back to the client."""


@dataclass
class Window:
    """Spikes accumulated since the last dashboard tick."""

    duration_ms: float = 0.0
    counts: np.ndarray | None = None
    compute_ms: list[float] = field(default_factory=list)


class BrainRunner:
    """Owns the simulator, the stimulus timers and the spike readouts.

    Args:
        weights: signed weight matrix of the brain to run.
        ids: FlyWire root ID per matrix index.
        groups: group name -> matrix indices (only groups present in this brain).
        cfg: server settings.
        mode: label for clients ("reduced", "full", or e.g. "toy" in tests).
        params: LIF constants.
    """

    def __init__(self, weights: sp.csr_matrix, ids: np.ndarray, groups: dict[str, np.ndarray],
                 cfg: ServerConfig, mode: str, params: LIFParams = LIFParams()) -> None:
        self.cfg = cfg
        self.mode = mode
        self.ids = np.asarray(ids, dtype=np.int64)
        self.id_strings = np.array([str(i) for i in self.ids])
        self.groups = groups
        self.sim = LIFSimulator(weights, params, seed=cfg.seed, noise=cfg.noise)
        for stim, group in cfg.input_groups.items():
            if group not in groups:
                raise ValueError(f"input group {group!r} is not in this brain")
            self.sim.set_input(stim, groups[group], 0.0)
        self._sample_rng = np.random.default_rng([cfg.seed, 1])
        self.stim_until_ms = {s: 0.0 for s in cfg.input_groups}
        self.light = 1.0
        self.mood = dict(cfg.initial_mood)
        self.seq = 0
        self.window = Window()
        # (duration_ms, readout spikes) of recent chunks, for the eating readout
        self._eat_hist: deque[tuple[float, int]] = deque()
        self.last_compute_ms = 0.0
        # Simulated time at which a new event takes effect: the start of the next
        # chunk (events never change the chunk that is already running).
        self.effective_t_ms = 0.0
        self.finished_t_ms = 0.0  # simulated time at the end of the last finished chunk

    # ------------------------------------------------------------ brain info
    def info(self) -> dict:
        """Static description of the running brain (sent in `hello`)."""
        return {
            "mode": self.mode,
            "backend": self.sim.backend,
            "n_neurons": int(self.sim.n),
            "chunk_ms": self.cfg.chunk_ms,
            "groups": {name: {"count": int(idx.size), "ids": self.id_strings[idx].tolist()}
                       for name, idx in self.groups.items()},
            "stimuli": {s: {"group": g, "rate_hz": self.cfg.input_rate_hz[s]}
                        for s, g in self.cfg.input_groups.items()},
            "light_is_brain_input": False,
        }

    # ---------------------------------------------------------------- events
    def handle_event(self, msg: object) -> dict:
        """Apply one phone message; return the reply. Raises EventError if invalid."""
        if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
            raise EventError("message must be a JSON object with a string 'type'")
        kind = msg["type"]
        now = self.effective_t_ms
        if kind in self.stim_until_ms:
            dur = msg.get("duration_ms", self.cfg.default_stimulus_ms)
            if isinstance(dur, bool) or not isinstance(dur, (int, float)) or not np.isfinite(dur) or dur < 0:
                raise EventError("duration_ms must be a non-negative number")
            dur = float(min(dur, self.cfg.max_stimulus_ms))
            # A new event extends a running stimulus; it never shortens it.
            self.stim_until_ms[kind] = max(self.stim_until_ms[kind], now + dur)
            return {"type": "ack", "event": kind, "duration_ms": dur,
                    "active_until_ms": self.stim_until_ms[kind], "t_ms": now}
        if kind == "light":
            level = msg.get("level")
            if isinstance(level, bool) or not isinstance(level, (int, float)) or not 0 <= level <= 1:
                raise EventError("level must be a number from 0 to 1")
            self.light = float(level)
            return {"type": "ack", "event": "light", "level": self.light, "t_ms": now}
        if kind == "stop":
            which = msg.get("stimulus", "all")
            names = list(self.stim_until_ms) if which == "all" else [which]
            if any(n not in self.stim_until_ms for n in names):
                raise EventError(f"stimulus must be one of {list(self.stim_until_ms) + ['all']}")
            for n in names:
                self.stim_until_ms[n] = now
            return {"type": "ack", "event": "stop", "stimulus": which, "t_ms": now}
        if kind == "ping":
            return {"type": "pong", "t": msg.get("t"), "server_time_ms": time.time() * 1000.0}
        raise EventError(f"unknown type {kind!r}")

    def reset_brain(self) -> None:
        """Return every neuron to rest and stop all stimuli."""
        self.sim.reset_state()
        self.stim_until_ms = {s: 0.0 for s in self.stim_until_ms}
        self._eat_hist.clear()
        self.window = Window()
        self.effective_t_ms = 0.0
        self.finished_t_ms = 0.0

    # ------------------------------------------------------------- the loop
    def apply_inputs(self) -> None:
        """Set each input rate for the next chunk from the stimulus timers."""
        now = self.sim.t_ms
        for stim, until in self.stim_until_ms.items():
            rate = self.cfg.input_rate_hz[stim] if until > now else 0.0
            if self.sim.rate(stim) != rate:
                self.sim.set_rate(stim, rate)
        self.effective_t_ms = now + self.cfg.chunk_ms

    def run_chunk(self) -> ChunkResult:
        """Advance the brain one chunk. The only call made from a worker thread."""
        t0 = time.perf_counter()
        res = self.sim.run(self.cfg.chunk_ms)
        self.last_compute_ms = (time.perf_counter() - t0) * 1000.0
        return res

    def accumulate(self, res: ChunkResult) -> None:
        """Add a finished chunk to the current window and the eating readout."""
        counts = res.counts(self.sim.n)
        w = self.window
        w.counts = counts if w.counts is None else w.counts + counts
        w.duration_ms += res.duration_ms
        w.compute_ms.append(self.last_compute_ms)
        self.finished_t_ms = res.t_start_ms + res.duration_ms
        readout = self.groups.get(self.cfg.eating_group)
        if readout is not None:
            self._eat_hist.append((res.duration_ms, int(counts[readout].sum())))
            total = sum(d for d, _ in self._eat_hist)
            while total - self._eat_hist[0][0] >= self.cfg.eating_window_ms:
                total -= self._eat_hist.popleft()[0]

    def window_ready(self) -> bool:
        """True once the window spans one dashboard tick period."""
        return self.window.duration_ms >= 1000.0 / self.cfg.broadcast_hz - 1e-9

    def readout_rate_hz(self) -> float:
        """Mean rate of the eating readout group over the recent window [Hz]."""
        readout = self.groups.get(self.cfg.eating_group)
        dur = sum(d for d, _ in self._eat_hist)
        if readout is None or dur == 0:
            return 0.0
        return sum(c for _, c in self._eat_hist) / readout.size / (dur / 1000.0)

    def game_state(self) -> dict:
        """Game-facing state: stimuli, light, brain readouts and (placeholder) mood."""
        now = self.window_end_ms()
        mn9 = self.readout_rate_hz()
        return {
            "stimuli_remaining_ms": {s: max(0.0, u - now) for s, u in self.stim_until_ms.items()},
            "light": self.light,
            "mn9_rate_hz": mn9,
            "eating": mn9 >= self.cfg.eating_threshold_hz,
            "mood": dict(self.mood),
            "mood_rules_active": False,
        }

    def make_tick(self, lag_ms: float = 0.0) -> dict:
        """Dashboard message for the finished window; starts a new window."""
        w, self.window = self.window, Window()
        counts = w.counts if w.counts is not None else np.zeros(self.sim.n, dtype=np.int64)
        sec = w.duration_ms / 1000.0 or 1.0
        spiking = np.flatnonzero(counts)
        sample = spiking
        if spiking.size > self.cfg.max_spike_ids:
            sample = np.sort(self._sample_rng.choice(spiking, self.cfg.max_spike_ids, replace=False))
        self.seq += 1
        return {
            "type": "tick",
            "seq": self.seq,
            "t_ms": self.window_end_ms(),
            "window_ms": w.duration_ms,
            "server_time_ms": time.time() * 1000.0,
            "group_counts": {g: int(counts[i].sum()) for g, i in self.groups.items()},
            "group_rates_hz": {g: float(counts[i].sum() / i.size / sec) for g, i in self.groups.items()},
            "total_spikes": int(counts.sum()),
            "n_spiking": int(spiking.size),
            "spiking_ids": self.id_strings[sample].tolist(),
            "spiking_ids_truncated": bool(spiking.size > sample.size),
            "inputs_hz": {s: self.sim.rate(s) for s in self.stim_until_ms},
            "game": self.game_state(),
            "perf": {"compute_ms": float(np.mean(w.compute_ms)) if w.compute_ms else 0.0,
                     "lag_ms": lag_ms},
        }

    def window_end_ms(self) -> float:
        """Simulated time at the end of the last finished chunk."""
        return self.finished_t_ms

    def phone_status(self) -> dict:
        """Small status message for the phone."""
        return {"type": "status", "t_ms": self.window_end_ms(), **self.game_state()}


def load_runner(cfg: ServerConfig) -> BrainRunner:
    """Build the runner for `cfg.brain_mode` from the connectome in data/."""
    from brain.connectome import load_connectome
    from brain.reduced import build_reduced_circuit
    from brain.validate import group_indices

    from brain.simulator import warm_up

    params = LIFParams()
    warm_up(params)  # so the first live chunk does not stall the loop
    conn = load_connectome()
    if cfg.brain_mode == "reduced":
        conn = build_reduced_circuit(conn).connectome
    elif cfg.brain_mode != "full":
        raise ValueError("brain_mode must be 'reduced' or 'full'")
    groups = group_indices(conn, skip_missing=True)
    return BrainRunner(conn.weight_matrix(params.w_syn), conn.ids, groups, cfg,
                       cfg.brain_mode, params)

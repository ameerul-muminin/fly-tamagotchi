"""All tunable server values (Phase 2). Brain/model values live in brain/config.py.

Game values here are project choices, not values from the paper.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from brain.config import CHUNK_MS, DEFAULT_INPUT_RATE_HZ, NoiseParams


@dataclass(frozen=True)
class ServerConfig:
    """Server, brain-loop and message settings."""

    # --- brain ---
    # "reduced" (19,698-neuron circuit, real time) or "full" (127,400 neurons,
    # about 65 ms per 50 ms chunk, slower than real time). Env var FLY_BRAIN overrides.
    brain_mode: str = field(default_factory=lambda: os.environ.get("FLY_BRAIN", "reduced"))
    seed: int = 0                        # Poisson input + noise random streams
    chunk_ms: float = CHUNK_MS           # simulated time per loop iteration
    realtime: bool = True                # pace the loop to wall-clock time
    # When the loop falls this far behind real time, it stops trying to catch up.
    max_lag_ms: float = 250.0
    # Background noise (a display choice, not in the reference model). Off by
    # default: every level tested either did nothing visible or eventually ignited
    # a self-sustained runaway state (see reports/PHASE_2_REPORT.md).
    noise: NoiseParams = NoiseParams(rate_hz=0.0, jump_mv=2.0)

    # --- inputs (phone events -> Poisson input rates) ---
    # stimulus name -> neuron group it drives
    input_groups: dict[str, str] = field(default_factory=lambda: {
        "sugar": "sugar_grn", "bitter": "bitter_grn"})
    input_rate_hz: dict[str, float] = field(default_factory=lambda: {
        "sugar": DEFAULT_INPUT_RATE_HZ, "bitter": DEFAULT_INPUT_RATE_HZ})
    default_stimulus_ms: float = 2000.0  # "sugar on for 2 s" when the phone sends no duration
    max_stimulus_ms: float = 10000.0

    # --- broadcasts ---
    broadcast_hz: float = 20.0           # dashboard tick cap
    phone_status_hz: float = 5.0         # phone status cap
    max_spike_ids: int = 500             # sampled spiking neuron IDs per dashboard tick
    client_queue_size: int = 8           # per-client buffer; oldest message dropped when full

    # --- readouts shown as game state ---
    eating_group: str = "mn9_primary"    # the Phase 1 readout neuron
    eating_window_ms: float = 500.0      # MN9 rate is averaged over this window
    eating_threshold_hz: float = 20.0    # same as Phase 1 `min_sugar_mn9_hz`
    # Placeholder mood values, sent unchanged until the Phase 5 rules exist.
    initial_mood: dict[str, float] = field(default_factory=lambda: {
        "hunger": 0.5, "happiness": 0.5, "energy": 1.0})

    # --- network ---
    host: str = "0.0.0.0"
    port: int = 8000


SERVER = ServerConfig()

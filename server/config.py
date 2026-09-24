"""All tunable server values (Phase 2; phone page values added in Phase 3). Brain/model values live in brain/config.py.

Game values here are project choices, not values from the paper.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from brain.config import CHUNK_MS, DEFAULT_INPUT_RATE_HZ, NoiseParams


@dataclass(frozen=True)
class PhoneConfig:
    """Phone controller page settings (Phase 3), served to the page by /api/phone-config.

    Project choices made before testing on a device, not measured values. Shake and
    camera values will need tuning on a real iPhone (PLAN.md Phase 6, item 4).
    """

    # --- tap -> sugar ---
    # Duration sent with each tap; None = let the server use default_stimulus_ms.
    tap_duration_ms: float | None = None

    # --- shake -> bitter (DeviceMotion) ---
    # Peak detector on |acceleration| with gravity removed, in m/s^2.
    shake_threshold_ms2: float = 15.0
    shake_min_peaks: int = 3             # peaks needed inside the window
    shake_window_ms: float = 800.0
    shake_cooldown_ms: float = 1500.0    # no second shake event this soon after one
    # Only accelerationIncludingGravity available: gravity is estimated with a
    # low-pass filter with this smoothing factor (per sample) and subtracted.
    gravity_lowpass_alpha: float = 0.1
    bitter_duration_ms: float | None = None  # None = server default

    # --- camera -> light (game-only on the server) ---
    camera_facing: str = "user"          # "user" (front) or "environment" (back)
    camera_sample_hz: float = 4.0        # brightness checks per second
    camera_width: int = 32               # frame is downscaled to this size before averaging
    camera_height: int = 24
    light_min_change: float = 0.05       # send when the level moves at least this much...
    light_max_interval_ms: float = 2000.0  # ...or at least this often
    dark_below: float = 0.15             # the page labels levels below this "dark"

    # --- feedback ---
    vibrate_pattern_ms: tuple[int, ...] = (80, 60, 80)  # on each eating onset

    # --- connection ---
    reconnect_min_ms: float = 500.0
    reconnect_max_ms: float = 8000.0


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
    # HTTPS (Safari needs it for motion and camera). PEM files, e.g. from mkcert.
    certfile: str | None = None
    keyfile: str | None = None
    # URL the dashboard QR code points to. Env var FLY_PUBLIC_URL overrides. When unset:
    # a running ngrok tunnel, else this machine's LAN address (see server/web.py).
    public_url: str | None = field(default_factory=lambda: os.environ.get("FLY_PUBLIC_URL"))
    ngrok_api: str = "http://127.0.0.1:4040/api/tunnels"  # ngrok's local inspection API
    ngrok_timeout_s: float = 0.3

    # --- phone page (Phase 3) ---
    phone: PhoneConfig = PhoneConfig()


SERVER = ServerConfig()


# --- Phase 4: dashboard ---------------------------------------------------
# Scripted session recorded by `python -m server.record_session` for the dashboard
# replay and tests: (label, seconds, phone messages sent at the start).
RECORD_SCRIPT: list[tuple[str, float, list[dict]]] = [
    ("baseline", 1.5, []),
    ("sugar", 3.0, [{"type": "sugar", "duration_ms": 3000}]),
    ("pause", 1.5, []),
    ("bitter", 2.5, [{"type": "bitter", "duration_ms": 2500}]),
    ("pause", 1.5, []),
    ("sugar+bitter", 3.0, [{"type": "sugar", "duration_ms": 3000},
                           {"type": "bitter", "duration_ms": 3000}]),
    ("pause", 1.0, []),
    ("dark", 3.0, [{"type": "light", "level": 0.05}]),
    ("light", 1.5, [{"type": "light", "level": 1.0}]),
]


@dataclass(frozen=True)
class DashboardChecks:
    """Pass/fail thresholds for `python -m server.validate_dashboard`, fixed before
    the first validation run (reports/PHASE_4_PLAN.md)."""

    live_seconds: float = 12.0               # live measurement length
    min_tick_rate_frac: float = 0.9          # received ticks/s >= this x broadcast_hz
    max_lost_frac: float = 0.02              # seq gaps / expected ticks
    min_median_fps: float = 30.0             # render frames per second (headless Chrome)
    max_p95_tick_age_ms: float = 150.0       # Date.now() - server_time_ms when drawn
    max_js_errors: int = 0
    replay_states: tuple[str, ...] = ("idle", "eating", "disgusted", "resting")
    replay_speed: float = 4.0                # replay speed-up for the replay check


DASHBOARD_CHECKS = DashboardChecks()

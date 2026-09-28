"""All tunable server values (Phase 2; phone page Phase 3; game rules Phase 5). Brain/model values live in brain/config.py.

Game values here are project choices, not values from the paper.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from brain.config import CHUNK_MS, DEFAULT_INPUT_RATE_HZ, NoiseParams


@dataclass(frozen=True)
class GameRules:
    """Phase 5 game rules (server/game.py). Project choices, not values from a paper.

    Rules read brain outputs (the MN9 eating readout, bitter-neuron spikes), time and the
    phone's light level. They never decide whether the fly eats. The one game -> brain link
    is `hunger_scales_sugar`: hunger sets how hard the phone's sugar drives the sugar GRNs.
    """

    # --- start values (also after revive / reset_brain) ---
    start_hunger: float = 0.5
    start_happiness: float = 0.7
    start_energy: float = 1.0

    # --- hunger ---
    hunger_rise_per_s: float = 1 / 240      # empty to starving in 4 minutes
    hunger_eat_per_s: float = 0.05          # while game.eating (MN9 readout) is true

    # --- happiness ---
    happy_eat_per_s: float = 0.03           # while eating
    unhappy_bitter_per_s: float = 0.05      # while bitter GRNs fire >= bitter_hz
    bitter_hz: float = 20.0                 # same as the dashboard's "disgusted" readout
    starving_at: float = 0.8                # hunger at or above this...
    unhappy_starving_per_s: float = 0.01    # ...costs this much happiness
    tired_below: float = 0.3                # energy below this is "tired"...
    unhappy_light_tired_per_s: float = 0.02 # ...and light while tired costs this much

    # --- energy and light ---
    dark_below: float = 0.15                # phone light level below this is dark (one
                                            # value for server, phone page and dashboard)
    energy_light_per_s: float = -1 / 300    # awake in the light: empty in 5 minutes
    energy_dark_per_s: float = 1 / 40       # resting in the dark: full in 40 s

    # --- fainting ---
    faint_after_s: float = 30.0             # this long at hunger 1.0 and the fly faints

    # --- optional game -> brain link (PLAN.md Phase 5, item 5) ---
    # Sugar input rate = base rate x (min_frac + (1 - min_frac) x hunger). Measured on the
    # reduced brain (reports/PHASE_5_PLAN.md): MN9 passes 20 Hz between 30 and 50 Hz of
    # input, so min_frac 0.2 (30 Hz) makes a sated fly's sugar too weak to drive MN9.
    hunger_scales_sugar: bool = True
    sugar_min_frac: float = 0.2


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
    dark_below: float = GameRules.dark_below  # the page labels levels below this "dark"

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
    # --- Phase 5 game rules ---
    game: GameRules = GameRules()

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


@dataclass(frozen=True)
class GameChecks:
    """Pass/fail thresholds for `python -m server.validate_game`, fixed in
    reports/PHASE_5_PLAN.md before the first validation run."""

    seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    hungry_start: float = 0.9
    eat_run_s: float = 60.0                  # continuous sugar
    min_drop_first_20s: float = 0.3          # G2
    tail_s: float = 20.0                     # G3/G4 look at the last this many seconds
    max_tail_eating_frac: float = 0.25       # G3 (scaling on)
    satiety_hunger_range: tuple[float, float] = (0.03, 0.35)  # G3
    min_tail_eating_frac_no_scaling: float = 0.75            # G4
    bitter_s: float = 3.0                    # G5
    min_happiness_drop: float = 0.1          # G5
    compare_s: float = 3.0                   # G6: sugar vs sugar+bitter, each this long
    compare_hunger: float = 0.9
    dark_s: float = 10.0                     # G7
    dark_start_energy: float = 0.5
    min_energy_gain: float = 0.2


GAME_CHECKS = GameChecks()

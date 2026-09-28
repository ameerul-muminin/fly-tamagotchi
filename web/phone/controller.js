// Phone controller logic with no browser dependencies (Phase 3).
//
// phone.js wires the DOM, sensors and WebSocket to this module; Node tests drive it
// with mock events. Nothing here decides fly behavior: the phone only sends inputs
// (reports/MESSAGE_FORMAT.md) and displays what the server reports.

/** Fallback values, identical to PhoneConfig in server/config.py (served by /api/phone-config). */
export const DEFAULTS = Object.freeze({
  tap_duration_ms: null,
  shake_threshold_ms2: 15.0,
  shake_min_peaks: 3,
  shake_window_ms: 800.0,
  shake_cooldown_ms: 1500.0,
  gravity_lowpass_alpha: 0.1,
  bitter_duration_ms: null,
  camera_facing: "user",
  camera_sample_hz: 4.0,
  camera_width: 32,
  camera_height: 24,
  light_min_change: 0.05,
  light_max_interval_ms: 2000.0,
  dark_below: 0.15,
  vibrate_pattern_ms: [80, 60, 80],
  reconnect_min_ms: 500.0,
  reconnect_max_ms: 8000.0,
});

/** Server config over the defaults; unknown keys are ignored. */
export function mergeConfig(cfg = {}) {
  const out = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) if (cfg[k] !== undefined) out[k] = cfg[k];
  return out;
}

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const hasXYZ = (a) => a != null && finite(a.x) && finite(a.y) && finite(a.z);

/**
 * Shake detector for DeviceMotion samples.
 *
 * A "peak" is |linear acceleration| rising above the threshold. A shake is
 * `shake_min_peaks` peaks inside `shake_window_ms`, then nothing for `shake_cooldown_ms`.
 * Uses `acceleration` (gravity removed by the OS) when present, else
 * `accelerationIncludingGravity` minus a low-pass gravity estimate.
 */
export class ShakeDetector {
  constructor(cfg = DEFAULTS) {
    this.cfg = mergeConfig(cfg);
    this.peaks = [];
    this.above = false;
    this.gravity = null;
    this.cooldownUntil = -Infinity;
  }

  /** Linear acceleration magnitude (m/s^2) for one sample, or null if unusable. */
  magnitude({ acc, accG }) {
    if (hasXYZ(acc)) return Math.hypot(acc.x, acc.y, acc.z);
    if (!hasXYZ(accG)) return null;
    const a = this.cfg.gravity_lowpass_alpha;
    if (this.gravity === null) this.gravity = { ...accG };
    else for (const k of ["x", "y", "z"]) this.gravity[k] += a * (accG[k] - this.gravity[k]);
    return Math.hypot(accG.x - this.gravity.x, accG.y - this.gravity.y, accG.z - this.gravity.z);
  }

  /** Feed one sample {acc, accG, t}; returns true when a shake is detected. */
  update(sample) {
    const m = this.magnitude(sample);
    if (m === null) return false;
    const t = sample.t;
    const isAbove = m >= this.cfg.shake_threshold_ms2;
    const rising = isAbove && !this.above;
    this.above = isAbove;
    if (t < this.cooldownUntil) return false;
    if (rising) this.peaks.push(t);
    this.peaks = this.peaks.filter((p) => t - p <= this.cfg.shake_window_ms);
    if (this.peaks.length >= this.cfg.shake_min_peaks) {
      this.peaks = [];
      this.cooldownUntil = t + this.cfg.shake_cooldown_ms;
      return true;
    }
    return false;
  }
}

/** Mean luma (Rec. 601 weights) of an RGBA pixel buffer, from 0 (black) to 1 (white). */
export function meanBrightness(rgba) {
  const n = Math.floor(rgba.length / 4);
  if (n === 0) return 0;
  let sum = 0;
  for (let i = 0; i < n * 4; i += 4) sum += 0.299 * rgba[i] + 0.587 * rgba[i + 1] + 0.114 * rgba[i + 2];
  return sum / (n * 255);
}

/** Decides when a new light level is worth sending (a real change, or a periodic refresh). */
export class LightReporter {
  constructor(cfg = DEFAULTS) {
    this.cfg = mergeConfig(cfg);
    this.lastLevel = null;
    this.lastT = -Infinity;
  }

  /** Returns the rounded level to send, or null to send nothing. */
  update(level, t) {
    const lv = Math.round(Math.min(1, Math.max(0, level)) * 1000) / 1000;
    const changed = this.lastLevel === null || Math.abs(lv - this.lastLevel) >= this.cfg.light_min_change;
    if (!changed && t - this.lastT < this.cfg.light_max_interval_ms) return null;
    this.lastLevel = lv;
    this.lastT = t;
    return lv;
  }
}

/** Reconnect delay after `attempt` failures: doubles from min up to max. */
export function backoffDelay(attempt, cfg = DEFAULTS) {
  const c = mergeConfig(cfg);
  return Math.min(c.reconnect_max_ms, c.reconnect_min_ms * 2 ** Math.max(0, attempt));
}

/** What the page shows for one `status` (or `hello.game`) message. Display only. */
export function statusView(s, cfg = DEFAULTS) {
  const c = mergeConfig(cfg);
  const mood = s.mood ?? {};
  const left = s.stimuli_remaining_ms ?? {};
  return {
    hunger: mood.hunger ?? null,
    happiness: mood.happiness ?? null,
    energy: mood.energy ?? null,
    moodPlaceholder: s.mood_rules_active !== true,
    eating: s.eating === true,
    mn9Hz: finite(s.mn9_rate_hz) ? s.mn9_rate_hz : 0,
    sugarLeftMs: left.sugar ?? 0,
    bitterLeftMs: left.bitter ?? 0,
    light: finite(s.light) ? s.light : null,
    // The server's own dark flag (Phase 5, one threshold everywhere); older servers
    // only send the level.
    dark: typeof s.dark === "boolean" ? s.dark : finite(s.light) && s.light < c.dark_below,
    fainted: s.fainted === true,
  };
}

/**
 * The phone controller.
 *
 * @param {object} deps
 * @param {(msg: object) => boolean} deps.send  sends one message; returns false if offline
 * @param {(pattern: number[]) => void} deps.vibrate  called on each eating onset
 * @param {() => number} deps.now  milliseconds (performance.now() in the browser)
 * @param {object} [deps.config]  PhoneConfig values from /api/phone-config
 * @param {(entry: object) => void} [deps.onLog]  every sent/received message, for display
 */
export function createController({ send, vibrate, now, config = {}, onLog = () => {} }) {
  const cfg = mergeConfig(config);
  const shake = new ShakeDetector(cfg);
  const light = new LightReporter(cfg);
  const state = {
    brain: null,
    status: null,
    view: null,
    eating: null, // null until the first hello/status: no vibration for a fly already eating
    eatOnsets: 0,
    lastLevel: null,
    rttMs: null,
    lastError: null,
  };

  const out = (msg) => {
    const ok = send(msg);
    onLog({ dir: "out", msg, ok });
    return ok;
  };
  const withDuration = (type, ms) => (ms == null ? { type } : { type, duration_ms: ms });

  function showStatus(s) {
    state.status = s;
    state.view = statusView(s, cfg);
    const eating = state.view.eating;
    if (eating && state.eating === false) {
      state.eatOnsets += 1;
      vibrate([...cfg.vibrate_pattern_ms]);
    }
    state.eating = eating;
  }

  return {
    config: cfg,
    state,
    /** Tap zone pressed: give sugar. */
    tap: () => out(withDuration("sugar", cfg.tap_duration_ms)),
    /** One DeviceMotion sample {acc, accG, t}; sends bitter on a shake. Returns true on a shake. */
    motion(sample) {
      if (!shake.update(sample)) return false;
      out(withDuration("bitter", cfg.bitter_duration_ms));
      return true;
    },
    /** One downscaled camera frame (RGBA); sends light when it changed. Returns the level. */
    frame(rgba) {
      const level = meanBrightness(rgba);
      state.lastLevel = level;
      const lv = light.update(level, now());
      if (lv !== null) out({ type: "light", level: lv });
      return level;
    },
    /** Latency probe; the pong fills state.rttMs. */
    ping: () => out({ type: "ping", t: now() }),
    /** Stop every stimulus now. */
    stop: () => out({ type: "stop", stimulus: "all" }),
    /** One parsed message from the server. */
    handle(msg) {
      onLog({ dir: "in", msg });
      switch (msg?.type) {
        case "hello":
          state.brain = msg.brain ?? null;
          if (msg.game) showStatus(msg.game);
          break;
        case "status":
          showStatus(msg);
          break;
        case "pong":
          if (finite(msg.t)) state.rttMs = now() - msg.t;
          break;
        case "error":
          state.lastError = msg.error;
          break;
        default:
          break;
      }
    },
    /** Connection lost: forget the eating state so a reconnect doesn't buzz. */
    disconnected() {
      state.eating = null;
    },
  };
}

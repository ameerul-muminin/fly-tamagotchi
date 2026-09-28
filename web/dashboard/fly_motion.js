// Pose logic for the 3D fly (fly3d.js), kept free of three.js so Node tests can run it.
// Display only: the state comes from state.js (eating = MN9 spikes, disgusted = bitter
// neuron spikes, resting = game-only light). Nothing here decides what the fly does.

/** Target pose per fly state. Units: radians, scene units (1 mm = CONFIG.fly3d.unitsPerMm). */
// `faint` (Phase 5): 1 = the fly lies on its back with its legs curled (the game rule
// "fainted": starving for too long). Only the flybody fly (fly_model3d.js) draws it.
export const POSES = {
  idle:      { proboscis: 0.0, headPitch: 0.0,  bodyX: 0.0,   bodyY: 0.0,   wingSpread: 0.10, buzz: 0, light: 1.0,  eyeGlow: 0.0, antennaDroop: 0, faint: 0 },
  eating:    { proboscis: 1.0, headPitch: 0.30, bodyX: 0.08,  bodyY: -0.05, wingSpread: 0.08, buzz: 0, light: 1.0,  eyeGlow: 0.0, antennaDroop: 0, faint: 0 },
  disgusted: { proboscis: 0.0, headPitch: -0.28, bodyX: -0.22, bodyY: 0.04, wingSpread: 0.38, buzz: 1, light: 1.0,  eyeGlow: 0.0, antennaDroop: 0, faint: 0 },
  resting:   { proboscis: 0.0, headPitch: 0.18, bodyX: 0.0,   bodyY: -0.12, wingSpread: 0.0,  buzz: 0, light: 0.18, eyeGlow: 1.0, antennaDroop: 1, faint: 0 },
  fainted:   { proboscis: 0.0, headPitch: 0.0,  bodyX: 0.0,   bodyY: 0.0,   wingSpread: 0.0,  buzz: 0, light: 0.8,  eyeGlow: 0.0, antennaDroop: 1, faint: 1 },
};

/** Exponential approach of `cur` to `target` with time constant `tau` (seconds). */
export function approach(cur, target, dt, tau) {
  if (tau <= 0) return target;
  return cur + (target - cur) * (1 - Math.exp(-dt / tau));
}

/** Move every pose value toward the target pose. Returns a new object. */
export function blendPose(cur, target, dt, tau) {
  const out = {};
  for (const k of Object.keys(target)) out[k] = approach(cur[k] ?? target[k], target[k], dt, tau);
  return out;
}

/**
 * Proboscis pumping rate (Hz) from the MN9 firing rate: MN9 drives the pump muscle, so
 * the drawn pump follows it. Zero when MN9 is silent.
 */
export function pumpHz(mn9Hz, cfg) {
  if (!(mn9Hz > 0)) return 0;
  return Math.min(cfg.pumpMaxHz, Math.max(cfg.pumpMinHz, mn9Hz / cfg.mn9HzPerPumpHz));
}

/** Grooming weight for the front legs (0 = planted, 1 = rubbing), by state and time. */
export function groomWeight(state, tSec, cfg) {
  if (state === "disgusted") return 1;
  if (state !== "idle") return 0;
  const phase = tSec % cfg.groomEverySec;
  return phase < cfg.groomForSec ? 1 : 0;
}

/**
 * Belly fullness 0..1: fills while the brain says the fly is eating, empties slowly.
 * A drawing of how long MN9 has been firing, not a game rule.
 */
export function nextFullness(full, eating, dt, cfg) {
  const f = eating ? full + dt / cfg.fillSec : full - dt / cfg.emptySec;
  return Math.min(1, Math.max(0, f));
}

/**
 * Render quality for a WebGL renderer name: "low" for software renderers (no GPU does the
 * drawing, so every pixel costs CPU time), "high" otherwise.
 */
export function qualityForRenderer(name) {
  return /swiftshader|llvmpipe|softpipe|software|basic render/i.test(String(name ?? "")) ? "low" : "high";
}

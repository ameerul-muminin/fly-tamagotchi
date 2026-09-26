// Every display setting of the dashboard, in one place.
// These are display choices only: they decide how brain output is drawn, never what
// the fly does. Eating comes from `tick.game.eating` (MN9 spikes, computed by the server).

export const CONFIG = {
  // --- fly face/body state (display readout, first match wins) ---
  // eating:    tick.game.eating (server: mn9_primary >= 20 Hz over 500 ms)
  // disgusted: bitter GRNs spiking at >= disgustBitterHz in this tick (brain activity)
  // resting:   tick.game.light <= darkLevel (light is game-only, not a brain input)
  // idle:      none of the above
  statePriority: ["eating", "disgusted", "resting", "idle"],
  disgustBitterHz: 20,
  darkLevel: 0.3,
  // A new state must hold for this long before the fly changes (stops flicker).
  stateHoldMs: 150,

  // --- activity chart ---
  chartWindowMs: 10000,        // simulated ms shown
  chartSeries: [
    { group: "sugar_grn", label: "Sugar GRNs" },
    { group: "bitter_grn", label: "Bitter GRNs" },
    { group: "mn9_primary", label: "MN9" },
  ],
  chartMaxHz: 200,             // y axis top (input drive is 150 Hz)

  // --- "Why it's doing that" meters ---
  meterMaxHz: { sugar_grn: 200, bitter_grn: 200, mn9_primary: 150 },  // full bar
  meterSmoothing: 0.35,        // per tick, 1 = no smoothing

  // --- 3D brain ---
  flashDecayMs: 300,           // a spike's flash fades with this time constant
  pointSizeBase: 2.0,          // px, neurons at rest
  pointSizeFlash: 6.0,         // extra px at full flash
  pointSizeGroupBonus: 3.0,    // extra px for sugar/bitter/MN9 neurons
  restAlpha: 0.16,
  cameraDistance: 1.9,         // camera distance in units of the point cloud's radius
  autoRotateDegPerSec: 6,

  // --- colors (group -> CSS color); shared by chart, legend and 3D view ---
  // Checked with the dataviz skill's validate_palette.js on surface #131a26 (dark):
  // lightness band, chroma, CVD separation (worst deutan dE 19.1) and contrast all pass.
  colors: {
    sugar_grn: "#1f9e62",
    bitter_grn: "#b35ae0",
    mn9_primary: "#c97d0a",
    mn9: "#c97d0a",
    other: "#7fb6ff",
    rest: "#8a93a6",
  },
  // Group used to color a neuron that is in several groups: first match wins.
  colorPriority: ["mn9_primary", "mn9", "sugar_grn", "bitter_grn"],

  // --- connection ---
  reconnectMs: 1500,
  wsPath: "/ws/dashboard",
  positionsPath: "/api/positions",
  phoneLinkRefreshMs: 5000,   // how often the phone QR panel re-checks the phone URL

  // --- 3D fly (fly3d.js, fly_motion.js); display only ---
  fly3d: {
    unitsPerMm: 1.08,          // model is 2.7 units long; a Drosophila female is ~2.5 mm
    poseTauSec: 0.18,          // how fast the pose follows a state change
    pumpMinHz: 2,              // proboscis pump rate while MN9 fires...
    pumpMaxHz: 8,
    mn9HzPerPumpHz: 14,        // ...= MN9 Hz / this, clamped to [min, max]
    groomEverySec: 7,          // idle fly rubs its front legs this often...
    groomForSec: 2.2,          // ...for this long
    fillSec: 12,               // belly fills over this much eating time
    emptySec: 40,              // and empties over this long
    maxPixelRatio: 1.5,
    fov: 30,                   // camera lens (degrees, vertical)...
    wideAspect: 1.3,           // ...widened for views narrower than this aspect...
    maxFov: 40,                // ...up to this
    shadowMapSize: 1024,
    // Quality: "auto" = "low" on a software renderer, else "high". URL ?quality= overrides.
    quality: "auto",
    lowPixelRatio: 0.6,        // render scale in low quality (the canvas is stretched)
    lowMaxFps: 20,             // low quality draws the fly at most this often
    slowFrameMs: 40,           // high quality drops shadows/reflections if the median
    slowCheckFrames: 120,      // frame over this many frames is slower than this
  },

  // --- "Hear the brain" (sound.js): spikes become sound, like a lab audio monitor ---
  sound: {
    volume: 0.5,
    // Max sounds per tick and per channel (a tick is 50 ms of brain time).
    maxPerTick: { mn9: 8, sugar: 5, bitter: 5, other: 7 },
    // Background crackle: clicks per tick = otherClickScale * sqrt(other spikes).
    otherClickScale: 0.25,
    // Sugar/bitter notes per tick = group spikes / this (then capped).
    groupSpikesPerNote: 30,
    scheduleAheadSec: 0.03,    // sounds for a tick are spread over the next 50 ms
  },
};

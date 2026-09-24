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
};

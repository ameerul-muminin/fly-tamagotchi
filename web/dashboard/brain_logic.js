// Brain-view logic without three.js, so Node tests can run it (tests/fun.test.mjs).
// Everything here reads server data; nothing decides what the brain or the fly does.

/**
 * Groups the phone input is driving right now: a stimulus counts when its input rate in
 * this tick is above zero (hello.brain.stimuli names the group, tick.inputs_hz the rate).
 * @returns {string[]} group names, e.g. ["sugar_grn"]
 */
export function stimulatedGroups(brain, inputsHz) {
  const out = [];
  for (const [name, stim] of Object.entries(brain?.stimuli ?? {})) {
    if ((inputsHz?.[name] ?? 0) > 0 && stim.group) out.push(stim.group);
  }
  return out;
}

/**
 * Index of the neuron nearest to (x, y) on screen, or -1 if none is within `maxPx`.
 * `screen` holds x, y pairs in CSS px (NaN = behind the camera). Simulated neurons are
 * the first `nSim`; they win ties by `simBonusPx`, since they are the ones that fire.
 * `visible(i)` (optional) skips neurons that are hidden.
 */
export function pickNearest(screen, x, y, maxPx, nSim = 0, simBonusPx = 0, visible = null) {
  let best = -1;
  let bestD = maxPx * maxPx;
  const n = screen.length / 2;
  for (let i = 0; i < n; i++) {
    const dx = screen[2 * i] - x;
    if (dx > maxPx || dx < -maxPx) continue;
    const dy = screen[2 * i + 1] - y;
    if (dy > maxPx || dy < -maxPx) continue;
    if (visible && !visible(i)) continue;
    let d = Math.sqrt(dx * dx + dy * dy);
    if (i < nSim) d = Math.max(0, d - simBonusPx);
    d *= d;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

/**
 * Which screen side each hemisphere is on, from the projected x of the mean left and mean
 * right neuron (the annotation table's `side` column). Rotating the view past 90 degrees
 * swaps them, so the labels stay true.
 * @returns {{left: "start"|"end", right: "start"|"end"}}
 */
export function sideLabels(leftScreenX, rightScreenX) {
  const leftFirst = leftScreenX <= rightScreenX;
  return { left: leftFirst ? "start" : "end", right: leftFirst ? "end" : "start" };
}

/** Title line of a neuron tooltip: cell type (or class) and side, from the annotations. */
export function neuronTitle(info) {
  const name = info.cell_type || info.cell_class || info.super_class || "Unnamed neuron";
  const side = info.side ? info.side[0].toUpperCase() + info.side.slice(1) : null;
  return side ? `${name} · ${side}` : name;
}

/** The count line above the brain: the whole simulated circuit, or the selected group. */
export function selectionText(selection, nSimPlaced, nAtlas, groupSizes) {
  if (!selection || selection === "all") {
    return `${nSimPlaced.toLocaleString("en-US")} of ${nAtlas.toLocaleString("en-US")} neurons simulated`;
  }
  const n = groupSizes[selection] ?? 0;
  return `${n.toLocaleString("en-US")} neuron${n === 1 ? "" : "s"} selected`;
}

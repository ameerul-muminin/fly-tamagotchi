// Brain-view logic (brain_logic.js) and the easing curve (ease.js): pure functions, no
// three.js, no browser.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { stimulatedGroups, pickNearest, sideLabels, neuronTitle, selectionText } from "../brain_logic.js";
import { cubicBezier } from "../ease.js";
import { parseRecording } from "../source.js";

const SAMPLE = fileURLToPath(new URL("../samples/session.jsonl", import.meta.url));
const BRAIN = {
  stimuli: { sugar: { group: "sugar_grn", rate_hz: 150 }, bitter: { group: "bitter_grn", rate_hz: 150 } },
};

test("stimulated groups come from the input rates in the tick, nothing else", () => {
  assert.deepEqual(stimulatedGroups(BRAIN, { sugar: 0, bitter: 0 }), []);
  assert.deepEqual(stimulatedGroups(BRAIN, { sugar: 150, bitter: 0 }), ["sugar_grn"]);
  assert.deepEqual(stimulatedGroups(BRAIN, { sugar: 150, bitter: 150 }).sort(), ["bitter_grn", "sugar_grn"]);
  assert.deepEqual(stimulatedGroups(null, { sugar: 150 }), []);
});

test("in the recorded session, a group is stimulated exactly while its input is on", () => {
  const messages = parseRecording(readFileSync(SAMPLE, "utf8")).map((l) => l.msg);
  const hello = messages.find((m) => m.type === "hello");
  const ticks = messages.filter((m) => m.type === "tick");
  let seen = 0;
  for (const t of ticks) {
    const g = stimulatedGroups(hello.brain, t.inputs_hz);
    assert.equal(g.includes("sugar_grn"), t.inputs_hz.sugar > 0);
    assert.equal(g.includes("bitter_grn"), t.inputs_hz.bitter > 0);
    seen += g.length;
  }
  assert.ok(seen > 0, "the sample drives some input");
});

test("pickNearest finds the closest point within the radius, else -1", () => {
  const screen = Float32Array.from([10, 10, 50, 50, 53, 50]);
  assert.equal(pickNearest(screen, 11, 11, 5), 0);
  assert.equal(pickNearest(screen, 52.8, 50, 5), 2);
  assert.equal(pickNearest(screen, 100, 100, 5), -1);
  assert.equal(pickNearest(Float32Array.from([NaN, NaN]), 0, 0, 5), -1, "points behind the camera are skipped");
});

test("pickNearest prefers simulated neurons by the bonus, and respects visibility", () => {
  // Point 0 is simulated (nSim = 1) and 3 px away; point 1 (backdrop) is 1 px away.
  const screen = Float32Array.from([13, 10, 11, 10]);
  assert.equal(pickNearest(screen, 10, 10, 8), 1);
  assert.equal(pickNearest(screen, 10, 10, 8, 1, 3), 0);
  assert.equal(pickNearest(screen, 10, 10, 8, 0, 0, (i) => i !== 1), 0);
});

test("L / R labels follow the projected hemispheres, so a turned brain swaps them", () => {
  assert.deepEqual(sideLabels(100, 300), { left: "start", right: "end" });
  assert.deepEqual(sideLabels(300, 100), { left: "end", right: "start" });
});

test("tooltip title uses the annotation's cell type and side, with fallbacks", () => {
  assert.equal(neuronTitle({ cell_type: "Pm5", side: "left" }), "Pm5 · Left");
  assert.equal(neuronTitle({ cell_type: null, cell_class: "gustatory", side: "right" }), "gustatory · Right");
  assert.equal(neuronTitle({ super_class: "central" }), "central");
  assert.equal(neuronTitle({}), "Unnamed neuron");
});

test("count line: simulated vs drawn for All, group size for a selection", () => {
  assert.equal(selectionText("all", 17101, 139248, {}), "17,101 of 139,248 neurons simulated");
  assert.equal(selectionText("sugar_grn", 17101, 139248, { sugar_grn: 21 }), "21 neurons selected");
  assert.equal(selectionText("mn9_primary", 17101, 139248, { mn9_primary: 1 }), "1 neuron selected");
});

test("cubicBezier matches the curve's ends, is monotonic, and linear() is identity", () => {
  const e = cubicBezier(0.77, 0, 0.175, 1);
  assert.equal(e(0), 0);
  assert.equal(e(1), 1);
  let prev = 0;
  for (let x = 0.01; x < 1; x += 0.01) {
    const y = e(x);
    assert.ok(y >= prev - 1e-9, `monotonic at ${x}`);
    prev = y;
  }
  // Against the curve itself: sample the parametric Bezier finely, look up y at x.
  const P = (a, b, t) => 3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t * t + t ** 3;
  for (const x of [0.2, 0.5, 0.7]) {
    let best = 0;
    for (let t = 0; t <= 1; t += 1e-5) if (Math.abs(P(0.77, 0.175, t) - x) < Math.abs(P(0.77, 0.175, best) - x)) best = t;
    assert.ok(Math.abs(e(x) - P(0, 1, best)) < 1e-3, `y at x=${x}`);
  }
  const lin = cubicBezier(0, 0, 1, 1);
  for (const x of [0.1, 0.33, 0.8]) assert.ok(Math.abs(lin(x) - x) < 1e-3);
});

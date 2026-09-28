// Tests for the 3D fly's pose logic, the gulp counter and "Hear the brain" (node --test).
// The rule under test: every animation and every sound follows the brain's output.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { CONFIG } from "../config.js";
import { DashboardState } from "../state.js";
import { parseRecording } from "../source.js";
import { POSES, approach, blendPose, pumpHz, groomWeight, nextFullness } from "../fly_motion.js";
import { planTick } from "../sound.js";

const SAMPLE = fileURLToPath(new URL("../samples/session.jsonl", import.meta.url));
const msgs = parseRecording(readFileSync(SAMPLE, "utf8")).map((l) => l.msg);
const ticks = msgs.filter((m) => m.type === "tick");
const F = CONFIG.fly3d;

// ------------------------------------------------------------------ fly motion
test("every fly state has a pose with the same keys", () => {
  const keys = Object.keys(POSES.idle).sort();
  for (const s of ["idle", "eating", "disgusted", "resting", "fainted"]) {
    assert.deepEqual(Object.keys(POSES[s]).sort(), keys, s);
  }
});

test("only the eating pose extends the proboscis", () => {
  for (const [s, pose] of Object.entries(POSES)) assert.equal(pose.proboscis > 0, s === "eating", s);
});

test("blendPose moves toward the target and settles on it", () => {
  let p = { ...POSES.idle };
  p = blendPose(p, POSES.eating, 0.05, F.poseTauSec);
  assert.ok(p.proboscis > 0 && p.proboscis < 1);
  for (let i = 0; i < 200; i++) p = blendPose(p, POSES.eating, 0.05, F.poseTauSec);
  assert.ok(Math.abs(p.proboscis - 1) < 1e-6);
  assert.equal(approach(3, 7, 0.1, 0), 7);
});

test("the pump follows MN9: silent MN9 means no pump, faster MN9 pumps faster (clamped)", () => {
  assert.equal(pumpHz(0, F), 0);
  assert.equal(pumpHz(NaN, F), 0);
  assert.equal(pumpHz(1, F), F.pumpMinHz);
  assert.ok(pumpHz(60, F) < pumpHz(90, F));
  assert.equal(pumpHz(10000, F), F.pumpMaxHz);
});

test("grooming: periodic when idle, constant when disgusted, never while eating", () => {
  assert.equal(groomWeight("idle", 0.1, F), 1);
  assert.equal(groomWeight("idle", F.groomForSec + 0.1, F), 0);
  assert.equal(groomWeight("idle", F.groomEverySec + 0.1, F), 1);
  assert.equal(groomWeight("disgusted", 3.3, F), 1);
  assert.equal(groomWeight("eating", 0.1, F), 0);
  assert.equal(groomWeight("resting", 0.1, F), 0);
});

test("belly fills only while eating and stays in [0, 1]", () => {
  assert.equal(nextFullness(0, false, 1, F), 0);
  const a = nextFullness(0, true, 1, F);
  assert.ok(a > 0);
  assert.equal(nextFullness(0.99, true, 5, F), 1);
  assert.ok(nextFullness(a, false, 1, F) < a);
});

// ------------------------------------------------------------------ gulps
test("gulps count eating onsets from game.eating in the recorded brain output", () => {
  const s = new DashboardState();
  let onsets = 0;
  let prev = false;
  for (const m of msgs) {
    s.apply(m);
    if (m.type === "tick") {
      if (m.game.eating && !prev) onsets += 1;
      prev = m.game.eating;
    }
  }
  assert.ok(onsets > 0, "the sample has eating");
  assert.equal(s.gulps, onsets);
});

test("reset_brain clears the gulp count", () => {
  const s = new DashboardState();
  for (const m of msgs) s.apply(m);
  s.apply({ type: "ack", event: "reset_brain" });
  assert.equal(s.gulps, 0);
});

// ------------------------------------------------------------------ sound
const tick = (counts, total) => ({
  group_counts: { sugar_grn: 0, bitter_grn: 0, mn9: 0, mn9_primary: 0, ...counts },
  total_spikes: total ?? Object.values(counts).reduce((a, b) => a + b, 0),
  window_ms: 50,
});

test("a silent brain plays nothing", () => {
  assert.deepEqual(planTick(tick({}), "idle", "idle"), { mn9: 0, sugar: 0, bitter: 0, other: 0, cue: null });
});

test("each MN9 spike is one thump, up to the cap", () => {
  assert.equal(planTick(tick({ mn9_primary: 3, mn9: 3 }), "idle", "idle").mn9, 3);
  assert.equal(planTick(tick({ mn9_primary: 99, mn9: 99 }), "idle", "idle").mn9, CONFIG.sound.maxPerTick.mn9);
});

test("group notes scale with spikes and are capped; other spikes become clicks", () => {
  const p = planTick(tick({ sugar_grn: 60, bitter_grn: 1 }, 61 + 400), "idle", "idle");
  assert.equal(p.sugar, 2);
  assert.equal(p.bitter, 1);
  assert.equal(p.other, Math.min(CONFIG.sound.maxPerTick.other, Math.round(CONFIG.sound.otherClickScale * 20)));
  const big = planTick(tick({ sugar_grn: 5000 }), "idle", "idle");
  assert.equal(big.sugar, CONFIG.sound.maxPerTick.sugar);
});

test("MN9 spikes are not counted twice as background clicks", () => {
  const p = planTick(tick({ mn9_primary: 4, mn9: 6 }, 6), "idle", "idle");
  assert.equal(p.other, 0);
});

test("cues play only on a change into eating or disgusted", () => {
  const t = tick({});
  assert.equal(planTick(t, "idle", "eating").cue, "gulp");
  assert.equal(planTick(t, "eating", "eating").cue, null);
  assert.equal(planTick(t, "eating", "disgusted").cue, "yuck");
  assert.equal(planTick(t, "eating", "idle").cue, null);
});

test("across the recorded session, sound happens only in ticks with spikes", () => {
  for (const t of ticks) {
    const p = planTick(t, "idle", "idle");
    const n = p.mn9 + p.sugar + p.bitter + p.other;
    if (t.total_spikes === 0) assert.equal(n, 0);
  }
  assert.ok(ticks.some((t) => planTick(t, "idle", "idle").mn9 > 0), "MN9 is heard in the sample");
});

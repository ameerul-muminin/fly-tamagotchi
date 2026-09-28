// Dashboard state reducer on the recorded server session (node --test).
// The sample is real reduced-brain output: python -m server.record_session --spawn

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { CONFIG } from "../config.js";
import { DashboardState, deriveFlyState } from "../state.js";
import { parseRecording } from "../source.js";

const SAMPLE = fileURLToPath(new URL("../samples/session.jsonl", import.meta.url));
const lines = parseRecording(readFileSync(SAMPLE, "utf8"));
const msgs = lines.map((l) => l.msg);
const ticks = msgs.filter((m) => m.type === "tick");

/** Replay the whole sample; returns the state and the fly state after every tick. */
function replay() {
  const s = new DashboardState();
  const trace = [];
  for (const m of msgs) {
    s.apply(m);
    if (m.type === "tick") trace.push({ tick: m, fly: s.flyState });
  }
  return { s, trace };
}

const inputsOf = (t) => [t.inputs_hz.sugar > 0 ? "sugar" : "", t.inputs_hz.bitter > 0 ? "bitter" : ""]
  .filter(Boolean).join("+") || "none";

test("sample starts with hello and has ticks for every scripted condition", () => {
  assert.equal(msgs[0].type, "hello");
  const seen = new Set(ticks.map(inputsOf));
  for (const c of ["none", "sugar", "bitter", "sugar+bitter"]) assert.ok(seen.has(c), c);
  assert.ok(ticks.some((t) => t.game.light <= CONFIG.darkLevel), "dark ticks present");
});

test("hello colors the highlighted groups, MN9 before sugar/bitter", () => {
  const { s } = replay();
  const g = s.brain.groups;
  assert.equal(s.colorGroup(g.mn9_primary.ids[0]), "mn9_primary");
  for (const id of g.sugar_grn.ids) assert.equal(s.colorGroup(id), "sugar_grn");
  for (const id of g.bitter_grn.ids) assert.equal(s.colorGroup(id), "bitter_grn");
  assert.equal(s.colorGroup("1"), "other");
});

test("deriveFlyState follows the brain readouts and the priority order", () => {
  const base = { group_rates_hz: { bitter_grn: 0 }, game: { eating: false, light: 1 } };
  assert.equal(deriveFlyState(base), "idle");
  assert.equal(deriveFlyState({ ...base, game: { eating: true, light: 1 } }), "eating");
  assert.equal(deriveFlyState({ ...base, group_rates_hz: { bitter_grn: 140 } }), "disgusted");
  assert.equal(deriveFlyState({ ...base, game: { eating: false, light: 0.05 } }), "resting");
  // eating outranks disgust (sugar+bitter while MN9 still fires): shown as eating
  assert.equal(deriveFlyState({ group_rates_hz: { bitter_grn: 140 }, game: { eating: true, light: 1 } }), "eating");
  // Phase 5: the server's dark flag decides resting; fainted outranks everything.
  assert.equal(deriveFlyState({ ...base, game: { eating: false, light: 0.05, dark: false } }), "idle");
  assert.equal(deriveFlyState({ ...base, game: { eating: false, light: 0.9, dark: true } }), "resting");
  assert.equal(deriveFlyState({ group_rates_hz: { bitter_grn: 140 }, game: { eating: true, light: 0, fainted: true } }),
    "fainted");
});

test("replaying the sample shows all four fly states", () => {
  const { s } = replay();
  assert.deepEqual([...s.statesSeen].sort(), ["disgusted", "eating", "idle", "resting"]);
});

test("each fly state appears only where the server data supports it", () => {
  const { trace } = replay();
  // Skip the first ticks after a change (hold time), then check steady state.
  const eatingTicks = trace.filter((x) => x.fly === "eating");
  assert.ok(eatingTicks.length > 20);
  // Eating is only ever shown while (or just after) the server said eating.
  for (const x of eatingTicks) {
    const i = trace.indexOf(x);
    const recent = trace.slice(Math.max(0, i - 4), i + 1);
    assert.ok(recent.some((r) => r.tick.game.eating), `eating shown at t=${x.tick.t_ms} without MN9`);
  }
  // Sugar alone in steady state -> eating.
  const sugarSteady = trace.filter((x) => inputsOf(x.tick) === "sugar" && x.tick.game.eating);
  assert.ok(sugarSteady.length > 20);
  assert.ok(sugarSteady.slice(5).every((x) => x.fly === "eating"));
  // Bitter alone -> disgusted, never eating.
  const bitter = trace.filter((x) => inputsOf(x.tick) === "bitter");
  assert.ok(bitter.slice(5).every((x) => x.fly === "disgusted"));
  // Dark with no taste input -> resting.
  const dark = trace.filter((x) => x.tick.game.light <= CONFIG.darkLevel && inputsOf(x.tick) === "none"
    && !x.tick.game.eating && x.tick.group_rates_hz.bitter_grn < CONFIG.disgustBitterHz);
  assert.ok(dark.length > 20);
  assert.ok(dark.slice(5).every((x) => x.fly === "resting"));
});

test("sugar+bitter lowers MN9 in the sample (brain effect the fly shows)", () => {
  const mean = (c) => {
    const ts = ticks.filter((t) => inputsOf(t) === c).slice(4); // skip onset
    return ts.reduce((a, t) => a + t.group_rates_hz.mn9_primary, 0) / ts.length;
  };
  assert.ok(mean("sugar") > 20, `sugar MN9 ${mean("sugar")}`);
  assert.ok(mean("sugar+bitter") < 0.5 * mean("sugar"), `sugar+bitter MN9 ${mean("sugar+bitter")}`);
});

test("chart keeps only the last chartWindowMs of simulated time", () => {
  const { s } = replay();
  const t = s.lastTick.t_ms;
  for (const { group } of CONFIG.chartSeries) {
    const series = s.series[group];
    assert.ok(series.length > 100, group);
    assert.ok(series[0].t >= t - CONFIG.chartWindowMs);
    assert.equal(series.at(-1).t, t);
  }
});

test("spike queue delivers every tick's IDs once", () => {
  const s = new DashboardState();
  let delivered = 0;
  let sent = 0;
  msgs.forEach((m, i) => {
    s.apply(m);
    if (m.type === "tick") sent += m.spiking_ids.length;
    if (i % 3 === 0) delivered += s.takeSpikes().reduce((a, ids) => a + ids.length, 0);
  });
  delivered += s.takeSpikes().reduce((a, ids) => a + ids.length, 0);
  assert.equal(delivered, sent);
  assert.ok(sent > 1000);
});

test("seq gaps are counted as lost ticks; t_ms going back clears the chart", () => {
  const s = new DashboardState();
  s.apply(msgs[0]);
  const [a, b, c] = ticks.slice(10, 13);
  s.apply(a);
  s.apply(c); // b dropped
  assert.equal(s.stats.lost, c.seq - a.seq - 1);
  s.apply({ ...b, seq: c.seq + 1, t_ms: 50 }); // after a reset t_ms restarts
  assert.equal(s.series.sugar_grn.length, 1);
});

test("reset_brain ack clears the session", () => {
  const s = new DashboardState();
  for (const m of msgs.slice(0, 40)) s.apply(m);
  assert.ok(s.lastTick);
  const before = s.stats.resets; // the recording itself holds the recorder's reset ack
  s.apply({ type: "ack", event: "reset_brain" });
  assert.equal(s.lastTick, null);
  assert.equal(s.series.mn9_primary.length, 0);
  assert.equal(s.stats.resets, before + 1);
});

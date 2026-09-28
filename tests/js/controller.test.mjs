// Unit tests for web/phone/controller.js with mock sensor events. Run: node --test tests/js
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  backoffDelay, createController, DEFAULTS, LightReporter, meanBrightness, mergeConfig,
  ShakeDetector, statusView,
} from "../../web/phone/controller.js";
import { coveredFrame, frame, motionSamples, shake, walking } from "./mock_sensors.mjs";

const countShakes = (det, samples) => samples.filter((s) => det.update(s)).length;

function harness(config = {}) {
  const sent = [];
  const vibrations = [];
  let t = 0;
  const ctl = createController({
    send: (m) => { sent.push(m); return true; },
    vibrate: (p) => vibrations.push(p),
    now: () => t,
    config,
  });
  return { ctl, sent, vibrations, setTime: (v) => { t = v; } };
}

const status = (eating, extra = {}) => ({
  type: "status", t_ms: 0, stimuli_remaining_ms: { sugar: 0, bitter: 0 }, light: 1,
  mn9_rate_hz: eating ? 80 : 0, eating, mood: { hunger: 0.5, happiness: 0.5, energy: 1 },
  mood_rules_active: false, ...extra,
});

test("a vigorous shake is detected exactly once", () => {
  assert.equal(countShakes(new ShakeDetector(), shake()), 1);
});

test("walking and a phone at rest are not shakes", () => {
  const det = new ShakeDetector();
  assert.equal(countShakes(det, walking()), 0);
  assert.equal(countShakes(det, motionSamples({ amp: 0, freq: 1, ms: 2000 })), 0);
});

test("a single jolt is not a shake", () => {
  const det = new ShakeDetector();
  const samples = motionSamples({ amp: 0, freq: 1, ms: 1000 });
  samples[10].acc = { x: 30, y: 0, z: 0 };
  assert.equal(countShakes(det, samples), 0);
});

test("cooldown: continuous shaking gives one event per cooldown period", () => {
  const det = new ShakeDetector();
  const samples = motionSamples({ amp: 25, freq: 5, ms: 3200 });
  // 3.2 s of shaking with a 1.5 s cooldown: at t ~ 0.2 s, ~1.8 s (and not a third before 3.4 s)
  assert.equal(countShakes(det, samples), 2);
});

test("works with gravity-only sensors (acceleration missing)", () => {
  assert.equal(countShakes(new ShakeDetector(), shake(0, { gravityOnly: true })), 1);
  assert.equal(countShakes(new ShakeDetector(), walking(0, { gravityOnly: true })), 0);
});

test("samples with no usable data are ignored", () => {
  const det = new ShakeDetector();
  assert.equal(det.update({ acc: null, accG: null, t: 0 }), false);
  assert.equal(det.update({ acc: { x: null, y: null, z: null }, accG: { x: NaN, y: 0, z: 0 }, t: 1 }), false);
});

test("brightness of mock frames", () => {
  assert.equal(meanBrightness(frame(0)), 0);
  assert.equal(meanBrightness(frame(255)), 1);
  assert.ok(Math.abs(meanBrightness(frame(255, 0, 0)) - 0.299) < 1e-9);
  assert.ok(meanBrightness(coveredFrame()) < 0.05);
  assert.equal(meanBrightness(new Uint8ClampedArray(0)), 0);
});

test("light is sent on a real change or periodically, not on jitter", () => {
  const lr = new LightReporter();
  assert.equal(lr.update(0.8, 0), 0.8);
  assert.equal(lr.update(0.82, 250), null); // jitter
  assert.equal(lr.update(0.1, 500), 0.1); // covered
  assert.equal(lr.update(0.11, 750), null);
  assert.equal(lr.update(0.11, 500 + DEFAULTS.light_max_interval_ms), 0.11); // refresh
  assert.equal(lr.update(1.7, 5000), 1); // clamped
});

test("tap sends sugar with the server default duration", () => {
  const { ctl, sent } = harness();
  ctl.tap();
  assert.deepEqual(sent, [{ type: "sugar" }]);
  const h2 = harness({ tap_duration_ms: 1500 });
  h2.ctl.tap();
  assert.deepEqual(h2.sent, [{ type: "sugar", duration_ms: 1500 }]);
});

test("shake sends bitter once; walking sends nothing", () => {
  const { ctl, sent } = harness();
  walking().forEach((s) => ctl.motion(s));
  assert.equal(sent.length, 0);
  shake(5000).forEach((s) => ctl.motion(s));
  assert.deepEqual(sent, [{ type: "bitter" }]);
});

test("camera frames send light levels (covered = dark)", () => {
  const { ctl, sent, setTime } = harness();
  ctl.frame(frame(220));
  setTime(250); ctl.frame(frame(222));
  setTime(500); ctl.frame(coveredFrame());
  assert.equal(sent.length, 2);
  assert.equal(sent[0].type, "light");
  assert.ok(sent[0].level > 0.8);
  assert.ok(sent[1].level <= 0.05);
});

test("vibrates once per eating onset, not on hello or while eating continues", () => {
  const { ctl, vibrations } = harness();
  ctl.handle({ type: "hello", brain: {}, game: status(true) }); // already eating on connect
  ctl.handle(status(true));
  assert.equal(vibrations.length, 0);
  ctl.handle(status(false));
  ctl.handle(status(true)); // onset 1
  ctl.handle(status(true));
  ctl.handle(status(false));
  ctl.handle(status(true)); // onset 2
  assert.equal(vibrations.length, 2);
  assert.deepEqual(vibrations[0], DEFAULTS.vibrate_pattern_ms);
  ctl.disconnected();
  ctl.handle({ type: "hello", brain: {}, game: status(true) });
  assert.equal(vibrations.length, 2);
});

test("status view is display only", () => {
  const v = statusView(status(false, { light: 0.05, stimuli_remaining_ms: { sugar: 1200, bitter: 0 } }));
  assert.equal(v.dark, true);
  assert.equal(v.sugarLeftMs, 1200);
  assert.equal(v.moodPlaceholder, true);
  assert.equal(v.hunger, 0.5);
  assert.equal(statusView(status(true, { mood_rules_active: true })).moodPlaceholder, false);
  // Phase 5: the server's dark flag wins over the local threshold; fainted is passed on.
  assert.equal(statusView(status(false, { light: 0.05, dark: false })).dark, false);
  assert.equal(statusView(status(false, { light: 0.9, dark: true })).dark, true);
  assert.equal(statusView(status(false, { fainted: true })).fainted, true);
  assert.equal(statusView(status(false)).fainted, false);
});

test("pong gives round-trip time; errors are kept", () => {
  const { ctl, sent, setTime } = harness();
  setTime(100); ctl.ping();
  setTime(112); ctl.handle({ type: "pong", t: sent[0].t, server_time_ms: 0 });
  assert.equal(ctl.state.rttMs, 12);
  ctl.handle({ type: "error", error: "nope" });
  assert.equal(ctl.state.lastError, "nope");
});

test("reconnect backoff doubles up to the cap", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 9].map((a) => backoffDelay(a)), [500, 1000, 2000, 4000, 8000, 8000, 8000]);
});

test("server config overrides defaults; unknown keys ignored", () => {
  const c = mergeConfig({ shake_threshold_ms2: 20, bogus: 1 });
  assert.equal(c.shake_threshold_ms2, 20);
  assert.equal("bogus" in c, false);
});

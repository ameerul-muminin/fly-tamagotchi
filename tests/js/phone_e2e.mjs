// End-to-end mock-event check: the real phone controller (web/phone/controller.js) talks
// to a running server over a real WebSocket, driven by mock tap, shake and camera events.
//
// Usage: node tests/js/phone_e2e.mjs <server base URL, e.g. http://127.0.0.1:8000>
// Prints each step; the last line is "RESULT <json>". Exit code 0 only if every check passes.
// Thresholds are in reports/PHASE_3_PLAN.md (set before the first run).

import { createController } from "../../web/phone/controller.js";
import { coveredFrame, frame, shake, walking } from "./mock_sensors.mjs";

const EAT_WITHIN_MS = 2000; // eating must start within 2 s of the tap
const DARK_MAX = 0.05; // covered camera
const BRIGHT_MIN = 0.8; // bright frame

const base = (process.argv[2] ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const wsUrl = base.replace(/^http/, "ws") + "/ws/phone";
const t0 = performance.now();
const now = () => performance.now();
const stamp = () => `${((now() - t0) / 1000).toFixed(2).padStart(6)} s`;
const log = (s) => console.log(`${stamp()}  ${s}`);
const short = (m) => JSON.stringify(m);

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), detail });
  log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? ` (${detail})` : ""}`);
}

// ---- config from the server, like the page does
const config = await (await fetch(`${base}/api/phone-config`)).json();

// ---- socket + controller
const ws = new WebSocket(wsUrl);
const waiters = [];
const vibrations = [];
let onsets = 0; // counted from the raw status stream, independently of the controller
let lastEating = null;
const statuses = [];

const ctl = createController({
  send: (m) => {
    if (ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(m));
    return true;
  },
  vibrate: (p) => { vibrations.push({ at: now(), pattern: p }); log(`  VIBRATE ${short(p)}`); },
  now,
  config,
  onLog: ({ dir, msg }) => {
    if (dir === "out" && msg.type !== "ping") log(`  phone -> ${short(msg)}`);
    if (dir === "in" && (msg.type === "ack" || msg.type === "error")) log(`  phone <- ${short(msg)}`);
  },
});

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  const game = msg.type === "hello" ? msg.game : msg.type === "status" ? msg : null;
  if (game) {
    if (msg.type === "status") {
      statuses.push({ at: now(), ...msg });
      if (game.eating && lastEating === false) onsets += 1;
    }
    lastEating = game.eating;
  }
  ctl.handle(msg);
  for (const w of [...waiters]) if (w.pred(msg)) { waiters.splice(waiters.indexOf(w), 1); w.resolve(msg); }
};

function waitFor(pred, timeoutMs, what) {
  return new Promise((resolve, reject) => {
    const w = { pred, resolve };
    waiters.push(w);
    setTimeout(() => {
      const i = waiters.indexOf(w);
      if (i >= 0) { waiters.splice(i, 1); reject(new Error(`timeout waiting for ${what}`)); }
    }, timeoutMs);
  });
}
const ackOf = (event, ms = 2000) => waitFor((m) => m.type === "ack" && m.event === event, ms, `ack ${event}`);
const statusWhere = (pred, ms, what) => waitFor((m) => m.type === "status" && pred(m), ms, what);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let exitCode = 1;
try {
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error(`cannot connect to ${wsUrl}`)); });
  const hello = await waitFor((m) => m.type === "hello", 5000, "hello");
  const b = hello.brain;
  log(`connected to ${wsUrl}: brain '${b.mode}', ${b.n_neurons} neurons, light_is_brain_input=${b.light_is_brain_input}`);
  check("hello received, fly not eating at rest", ctl.state.eating === false, `eating=${ctl.state.eating}`);

  // ---- 1. tap -> sugar -> brain -> eating -> vibrate
  log("STEP 1: mock tap on the sugar zone");
  const tapAt = now();
  ctl.tap();
  const ack1 = await ackOf("sugar");
  check("tap sent sugar and the server acked it", ack1.event === "sugar", `active_until_ms=${ack1.active_until_ms}`);
  const eat1 = await statusWhere((m) => m.eating, EAT_WITHIN_MS + 1000, "eating").catch(() => null);
  const eatMs = eat1 ? now() - tapAt : null;
  check(`fly starts eating within ${EAT_WITHIN_MS} ms of the tap`, eat1 && eatMs <= EAT_WITHIN_MS,
    eat1 ? `${eatMs.toFixed(0)} ms, MN9 ${eat1.mn9_rate_hz.toFixed(1)} Hz` : "never ate");
  check("phone vibrated on the eating onset", vibrations.length === 1, `${vibrations.length} vibration(s)`);
  await statusWhere((m) => !m.eating, 8000, "eating to stop");
  log("  sugar ran out, fly stopped eating");

  // ---- 2. shake -> bitter (walking first: must not count)
  log("STEP 2: mock DeviceMotion: 3 s of walking, then a hard shake");
  let bitterSent = 0;
  for (const s of walking(now())) if (ctl.motion(s)) bitterSent += 1;
  check("walking motion sends no bitter", bitterSent === 0, `${bitterSent} shake(s) detected`);
  const ackBitter = ackOf("bitter");
  for (const s of shake(now() + 5000)) if (ctl.motion(s)) bitterSent += 1;
  const ack2 = await ackBitter;
  check("shake sent bitter once and the server acked it", bitterSent === 1 && ack2.event === "bitter",
    `${bitterSent} shake(s), active_until_ms=${ack2.active_until_ms}`);
  // Informational only: sugar while bitter is running (the brain decides; no phone rule).
  ctl.tap();
  await ackOf("sugar");
  await sleep(1500);
  const both = statuses.filter((s) => s.stimuli_remaining_ms.sugar > 0 && s.stimuli_remaining_ms.bitter > 0);
  log(`  info: tap during bitter -> MN9 max ${Math.max(0, ...both.map((s) => s.mn9_rate_hz)).toFixed(1)} Hz ` +
      `over ${both.length} status messages (eating in ${both.filter((s) => s.eating).length})`);
  ctl.stop();
  await ackOf("stop");
  await statusWhere((m) => !m.eating && m.stimuli_remaining_ms.bitter === 0, 8000, "stimuli to end");

  // ---- 3. camera -> light
  log("STEP 3: mock camera frames: bright room, then camera covered by a hand");
  const ackBright = ackOf("light");
  const bright = ctl.frame(frame(230, 225, 210));
  const a3 = await ackBright;
  check(`bright frame sends light >= ${BRIGHT_MIN}`, a3.level >= BRIGHT_MIN, `measured ${bright.toFixed(3)}, acked ${a3.level}`);
  const ackDark = ackOf("light");
  const dark = ctl.frame(coveredFrame());
  const a4 = await ackDark;
  check(`covered camera sends light <= ${DARK_MAX}`, a4.level <= DARK_MAX, `measured ${dark.toFixed(3)}, acked ${a4.level}`);
  const st = await statusWhere((m) => m.light === a4.level, 2000, "status with the new light level");
  check("status reports the dark level back; phone shows 'dark'", ctl.state.view.dark === true,
    `status.light=${st.light}`);
  ctl.frame(frame(230, 225, 210));
  await ackOf("light");

  // ---- 4. second meal: one vibration per onset
  log("STEP 4: second tap");
  ctl.tap();
  await ackOf("sugar");
  await statusWhere((m) => m.eating, EAT_WITHIN_MS + 1000, "second eating onset");
  await sleep(600);
  check("vibrations == eating onsets seen in the raw status stream", vibrations.length === onsets && onsets >= 2,
    `${vibrations.length} vibration(s), ${onsets} onset(s)`);

  // ---- latency probe
  ctl.ping();
  await waitFor((m) => m.type === "pong", 2000, "pong");
  log(`ping round trip ${ctl.state.rttMs.toFixed(1)} ms`);
  exitCode = checks.every((c) => c.ok) ? 0 : 1;
} catch (err) {
  check("scenario completed", false, err.message);
}
ws.close();
const passed = checks.filter((c) => c.ok).length;
console.log(`${passed}/${checks.length} checks passed`);
console.log(`RESULT ${JSON.stringify({ ok: exitCode === 0, checks, vibrations: vibrations.length, onsets, rttMs: ctl.state.rttMs })}`);
process.exit(exitCode);

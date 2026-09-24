// Wires a message source to the state, the fly, the mood bars, the chart and the 3D brain.
// URL options: ?replay=samples/session.jsonl&speed=1&loop=1  (default: live server)

import { CONFIG } from "./config.js";
import { DashboardState } from "./state.js";
import { createFly } from "./fly.js";
import { ActivityChart } from "./chart.js";
import { LiveSource, ReplaySource } from "./source.js";

const $ = (sel) => document.querySelector(sel);
const params = new URLSearchParams(location.search);
const state = new DashboardState();
const fly = createFly($("#fly"));
const chart = new ActivityChart($("#chart"), $("#chart-tip"));

const replayUrl = params.get("replay");
const source = replayUrl
  ? new ReplaySource(replayUrl, Number(params.get("speed") || 1), params.get("loop") === "1")
  : new LiveSource(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${CONFIG.wsPath}`);

// ---- measurements read by the validation script (server/validate_dashboard.py) ----
const perf = {
  jsErrors: [],
  frames: [],          // frame intervals [ms], last 240
  workMs: [],          // JS time spent inside each frame callback [ms], last 240
  tickAges: [],        // Date.now() - server_time_ms when a tick was first drawn, last 400
  ticksDrawn: 0,
  firstTickWallMs: null,
  lastTickWallMs: null,
  maxLit: 0,
  pointsDrawn: 0,
  chartPoints: 0,
};
addEventListener("error", (e) => perf.jsErrors.push(String(e.message)));
addEventListener("unhandledrejection", (e) => perf.jsErrors.push(String(e.reason)));

let brain = null;
let positions = null;
let lastDrawnSeq = null;

function setConn(text) {
  const el = $("#conn");
  el.textContent = text;
  el.className = "pill " + (text === "live" ? "live" : text.startsWith("replay") ? "replay" : "down");
}

function onMessage(msg) {
  state.apply(msg);
  if (msg.type === "hello") {
    const b = msg.brain;
    $("#brain-info").textContent = `${b.mode} brain · ${b.n_neurons.toLocaleString()} neurons · ${b.backend}`;
    buildBrainView();
  } else if (msg.type === "tick") {
    const now = Date.now();
    perf.firstTickWallMs ??= now;
    perf.lastTickWallMs = now;
  }
}

async function loadPositions() {
  const res = await fetch(CONFIG.positionsPath);
  if (!res.ok) throw new Error(`positions: HTTP ${res.status}`);
  positions = await res.json();
  const unplaced = Object.entries(positions.groups_unplaced).filter(([, v]) => v.length);
  $("#brain-note").textContent =
    `${positions.n_placed.toLocaleString()} of ${positions.n_neurons.toLocaleString()} neurons have a position ` +
    `(FlyWire v630 IDs unchanged in the v783 annotations); the rest are not drawn.` +
    (unplaced.length ? ` Unplaced in groups: ${unplaced.map(([g, v]) => `${g} ${v.length}`).join(", ")}.` : "") +
    ` Only a sample of up to 500 spiking neurons per tick is sent.`;
  buildBrainView();
}

async function buildBrainView() {
  if (brain || !positions || !state.brain) return;
  try {
    const { BrainView } = await import("./brain3d.js");
    if (brain) return;
    brain = new BrainView($("#brain3d"), positions, (id) => state.colorGroup(id));
    perf.pointsDrawn = brain.n;
    $("#brain-msg").remove();
    state.takeSpikes(); // don't flash the backlog from before the view existed
  } catch (err) {
    $("#brain-msg").textContent = `3D view unavailable: ${err.message}. (three.js loads from cdn.jsdelivr.net.)`;
    perf.jsErrors.push(`brain3d: ${err.message}`);
  }
}

function legend() {
  const items = [
    ["sugar_grn", "Sugar taste neurons"],
    ["bitter_grn", "Bitter taste neurons"],
    ["mn9_primary", "MN9 feeding motor neuron"],
    ["other", "Other spiking neurons"],
  ];
  $("#legend").innerHTML = items
    .map(([g, label]) => `<li><i style="background:${CONFIG.colors[g]}"></i>${label}</li>`)
    .join("");
}

function caption(s, tick) {
  const g = tick.game;
  switch (s) {
    case "eating":
      return `Eating: MN9 is firing at ${g.mn9_rate_hz.toFixed(0)} Hz`;
    case "disgusted":
      return `Disgusted: bitter neurons firing at ${tick.group_rates_hz.bitter_grn.toFixed(0)} Hz` +
        (g.mn9_rate_hz > 0 ? `, MN9 at ${g.mn9_rate_hz.toFixed(0)} Hz` : ", MN9 silent");
    case "resting":
      return `Resting in the dark (light ${Math.round(g.light * 100)}%)`;
    default:
      return "Idle: no taste input";
  }
}

const last = {};
function setText(sel, text) {
  if (last[sel] !== text) {
    last[sel] = text;
    $(sel).textContent = text;
  }
}

function updateDom() {
  const tick = state.lastTick;
  const game = state.game;
  if (game) {
    for (const bar of document.querySelectorAll(".bar")) {
      const v = game.mood[bar.dataset.key] ?? 0;
      const pct = `${Math.round(v * 100)}%`;
      if (bar.dataset.v !== pct) {
        bar.dataset.v = pct;
        bar.querySelector(".fill").style.width = pct;
        bar.querySelector("output").textContent = pct;
      }
    }
    setText("#mood-note", game.mood_rules_active
      ? "Mood rules are on."
      : "Placeholder values: the mood rules arrive in Phase 5.");
  }
  if (!tick) return;
  fly.setState(state.flyState, { sugar: tick.inputs_hz.sugar > 0, bitter: tick.inputs_hz.bitter > 0 });
  $(".fly-panel").classList.toggle("dark", state.flyState === "resting");
  setText("#fly-caption", caption(state.flyState, tick));
  setText("#clock", `t = ${(tick.t_ms / 1000).toFixed(1)} s`);
  const fps = medianFps();
  const age = percentile(perf.tickAges, 0.95);
  setText("#stats",
    `ticks ${state.stats.ticks} · lost ${state.stats.lost} · spiking ${tick.n_spiking} · ` +
    `spikes ${tick.total_spikes} · compute ${tick.perf.compute_ms.toFixed(1)} ms/chunk · ` +
    `lag ${tick.perf.lag_ms.toFixed(0)} ms · ${fps.toFixed(0)} fps` +
    (source.kind === "live" && age != null ? ` · tick age p95 ${age.toFixed(0)} ms` : "") +
    (brain ? ` · lit ${brain.litCount}` : ""));
}

function percentile(xs, q) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

function medianFps() {
  const m = percentile(perf.frames, 0.5);
  return m ? 1000 / m : 0;
}

let prevFrame = performance.now();
function frame(now) {
  perf.frames.push(now - prevFrame);
  if (perf.frames.length > 240) perf.frames.shift();
  prevFrame = now;

  const batches = state.takeSpikes();
  if (brain) {
    for (const ids of batches) brain.spike(ids);
    perf.maxLit = Math.max(perf.maxLit, brain.render(source.paused === true));
  }
  const tick = state.lastTick;
  if (tick && tick.seq !== lastDrawnSeq) {
    lastDrawnSeq = tick.seq;
    perf.ticksDrawn += 1;
    perf.tickAges.push(Date.now() - tick.server_time_ms);
    if (perf.tickAges.length > 400) perf.tickAges.shift();
  }
  perf.chartPoints = chart.update(state);
  updateDom();
  perf.workMs.push(performance.now() - now);
  if (perf.workMs.length > 240) perf.workMs.shift();
  requestAnimationFrame(frame);
}

$("#reset").addEventListener("click", () => {
  source.send({ type: "reset_brain" });
  if (source.kind === "replay") state.clearSession();
});

// Read by server/validate_dashboard.py over the Chrome DevTools protocol.
window.__dash = {
  state,
  perf,
  source,
  snapshot() {
    return {
      source: source.kind,
      replayDone: source.kind === "replay" ? source.done : null,
      hasBrain: !!state.brain,
      brainView: !!brain,
      pointsDrawn: perf.pointsDrawn,
      maxLit: perf.maxLit,
      flashedTotal: brain?.flashedTotal ?? 0,
      ticks: state.stats.ticks,
      lost: state.stats.lost,
      ticksDrawn: perf.ticksDrawn,
      tickWallSpanMs: perf.lastTickWallMs - perf.firstTickWallMs,
      statesSeen: [...state.statesSeen],
      flyState: state.flyState,
      flyDomState: $("#fly svg").dataset.state ?? null,
      chartPoints: perf.chartPoints,
      medianFps: medianFps(),
      medianFrameWorkMs: percentile(perf.workMs, 0.5),
      p95FrameWorkMs: percentile(perf.workMs, 0.95),
      p95TickAgeMs: percentile(perf.tickAges, 0.95),
      jsErrors: perf.jsErrors,
      caption: $("#fly-caption").textContent,
      mood: Object.fromEntries([...document.querySelectorAll(".bar")].map((b) => [b.dataset.key, b.dataset.v])),
    };
  },
};

legend();
loadPositions().catch((err) => {
  $("#brain-msg").textContent = `No neuron positions: ${err.message}`;
  perf.jsErrors.push(`positions: ${err.message}`);
});
source.start(onMessage, setConn);
requestAnimationFrame(frame);

// Wires a message source to the state, the fly, the meters, the mood bars, the chart,
// the 3D brain and the brain sounds.
// URL options: ?replay=samples/session.jsonl&speed=1&loop=1  (default: live server)

import { CONFIG } from "./config.js";
import { DashboardState } from "./state.js";
import { createFly } from "./fly.js";
import { ActivityChart } from "./chart.js";
import { LiveSource, ReplaySource } from "./source.js";
import { BrainSound } from "./sound.js";

const $ = (sel) => document.querySelector(sel);
const params = new URLSearchParams(location.search);
const state = new DashboardState();
// The 2D fly shows at once; the 3D fly replaces it when three.js has loaded.
let fly = createFly($("#fly"));
const sound = new BrainSound();
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
    const eat = b.eating;
    const line = $("#eat-line");
    if (eat) {
      line.hidden = false;
      line.style.left = `${Math.min(100, (100 * eat.threshold_hz) / CONFIG.meterMaxHz.mn9_primary)}%`;
      line.dataset.label = `eats at ${eat.threshold_hz} Hz`;
    }
    buildBrainView();
  } else if (msg.type === "tick") {
    sound.play(msg, state.flyState);
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

const STATE_WORD = { eating: "Eating", disgusted: "Disgusted", resting: "Resting", idle: "Idle" };

// Meter readouts, smoothed a little so a 50 ms tick doesn't flicker.
const meters = { sugar_grn: 0, bitter_grn: 0, mn9_primary: 0, seq: null };

function updateMeters(tick) {
  const eat = state.brain?.eating;
  const raw = {
    sugar_grn: tick.group_rates_hz.sugar_grn ?? 0,
    bitter_grn: tick.group_rates_hz.bitter_grn ?? 0,
    // The eating readout itself: MN9 averaged over the server's eating window.
    mn9_primary: tick.game.mn9_rate_hz ?? 0,
  };
  for (const el of document.querySelectorAll(".meter")) {
    const g = el.dataset.group;
    meters[g] += CONFIG.meterSmoothing * (raw[g] - meters[g]);
    const pct = Math.min(100, (100 * meters[g]) / CONFIG.meterMaxHz[g]);
    el.querySelector(".fill").style.width = `${pct.toFixed(1)}%`;
    el.querySelector("output").textContent = `${Math.round(meters[g])} Hz`;
  }
  const over = eat ? raw.mn9_primary >= eat.threshold_hz : tick.game.eating;
  $('.meter[data-group="mn9_primary"]').classList.toggle("over", !!over);
  setText("#why-text", whyText(tick, raw));
}

/** One or two plain sentences on what the brain is doing right now. */
function whyText(tick, r) {
  const thr = state.brain?.eating?.threshold_hz;
  const line = thr != null ? `the ${thr} Hz eating line` : "the eating line";
  const hz = (x) => `${Math.round(x)} Hz`;
  const sugarOn = tick.inputs_hz.sugar > 0;
  const bitterOn = tick.inputs_hz.bitter > 0;
  let s;
  if (tick.game.eating) {
    s = `Sugar neurons fire at ${hz(r.sugar_grn)} and drive MN9 to ${hz(r.mn9_primary)}, above ${line}. The fly eats.`;
  } else if (sugarOn && bitterOn) {
    s = `Sugar and bitter neurons both fire. MN9 only reaches ${hz(r.mn9_primary)}, below ${line}, so the fly doesn't eat. ` +
      "The wiring works out the mix; there is no bitter rule.";
  } else if (sugarOn) {
    s = `Sugar neurons fire at ${hz(r.sugar_grn)}. MN9 is at ${hz(r.mn9_primary)} and has to pass ${line}.`;
  } else if (bitterOn) {
    s = `Bitter neurons fire at ${hz(r.bitter_grn)}. MN9 stays at ${hz(r.mn9_primary)}: nothing tells the fly to eat.`;
  } else {
    s = "No taste input, so the taste neurons are quiet. Tap the phone to give sugar, or shake it for bitter.";
  }
  if (tick.game.light <= CONFIG.darkLevel) {
    s += " It's dark, so the fly rests. That part is a game rule: light isn't wired into this brain.";
  }
  return s;
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
  fly.setState(state.flyState, { sugar: tick.inputs_hz.sugar > 0, bitter: tick.inputs_hz.bitter > 0 },
    { mn9Hz: tick.game.mn9_rate_hz });
  const stage = $("#stage");
  if (stage.dataset.state !== state.flyState) stage.dataset.state = state.flyState;
  setText("#fly-state-word", STATE_WORD[state.flyState] ?? "Idle");
  setText("#fly-caption", caption(state.flyState, tick));
  setText("#gulps", String(state.gulps));
  if (tick.seq !== meters.seq) {
    meters.seq = tick.seq;
    updateMeters(tick);
  }
  setText("#clock", `t = ${(tick.t_ms / 1000).toFixed(1)} s`);
  const fps = medianFps();
  const age = percentile(perf.tickAges, 0.95);
  setText("#stats", [
    `ticks ${state.stats.ticks}`, `lost ${state.stats.lost}`, `spiking ${tick.n_spiking}`,
    `spikes ${tick.total_spikes}`, `compute ${tick.perf.compute_ms.toFixed(1)} ms per 50 ms chunk`,
    `lag ${tick.perf.lag_ms.toFixed(0)} ms`, `${fps.toFixed(0)} fps`,
    ...(source.kind === "live" && age != null ? [`tick age p95 ${age.toFixed(0)} ms`] : []),
    ...(brain ? [`lit ${brain.litCount}`] : []),
  ].join("   "));
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
  fly.render(now);
  perf.chartPoints = chart.update(state);
  updateDom();
  perf.workMs.push(performance.now() - now);
  if (perf.workMs.length > 240) perf.workMs.shift();
  requestAnimationFrame(frame);
}

$("#sound").addEventListener("click", async () => {
  if (sound.on) {
    sound.disable();
  } else {
    try {
      await sound.enable();
    } catch (err) {
      setText("#sound-label", "No audio in this browser");
      return;
    }
  }
  $("#sound").setAttribute("aria-pressed", String(sound.on));
  setText("#sound-label", sound.on ? "Listening" : "Hear the brain");
});

$("#reset").addEventListener("click", () => {
  source.send({ type: "reset_brain" });
  if (source.kind === "replay") state.clearSession();
});

// Read by server/validate_dashboard.py over the Chrome DevTools protocol.
window.__dash = {
  state,
  perf,
  source,
  get fly() { return fly; },
  get brain() { return brain; },
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
      flyDomState: $("#fly").dataset.state ?? null,
      flyView: $("#fly canvas") ? "3d" : "2d",
      gulps: state.gulps,
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
import("./fly3d.js")
  .then(({ Fly3D }) => {
    const el = $("#fly");
    el.innerHTML = "";
    fly = new Fly3D(el, CONFIG, params.get("quality") ?? CONFIG.fly3d.quality);
  })
  .catch((err) => console.warn(`3D fly unavailable, showing the 2D fly: ${err.message}`));
loadPositions().catch((err) => {
  $("#brain-msg").textContent = `No neuron positions: ${err.message}`;
  perf.jsErrors.push(`positions: ${err.message}`);
});
source.start(onMessage, setConn);
requestAnimationFrame(frame);

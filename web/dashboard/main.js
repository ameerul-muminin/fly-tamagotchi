// Wires a message source to the state, the fly, the meters, the mood bars, the chart,
// the 3D brain (selection chips, neuron tooltip, L/R labels) and the brain sounds.
// URL options: ?replay=samples/session.jsonl&speed=1&loop=1  (default: live server)

import { CONFIG } from "./config.js";
import { DashboardState } from "./state.js";
import { createFly } from "./fly.js";
import { ActivityChart } from "./chart.js";
import { LiveSource, ReplaySource } from "./source.js";
import { BrainSound } from "./sound.js";
import { stimulatedGroups, sideLabels, neuronTitle, selectionText } from "./brain_logic.js";

const $ = (sel) => document.querySelector(sel);
const params = new URLSearchParams(location.search);
const state = new DashboardState();
// The 2D fly shows at once. The flybody model replaces it once three.js and
// /api/fly_model.glb load; the simple 3D fly (fly3d.js) is the fallback without the model.
let fly = createFly($("#fly"));
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
for (const [k, v] of Object.entries(CONFIG.brain.colors)) document.documentElement.style.setProperty(`--c-${k}`, v);
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
let atlas = null;
let lastDrawnSeq = null;
let selection = "all";

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
  // A 404 here usually means a server started before this page's code: restart it.
  const get = async (url, kind) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}${r.status === 404 ? " (restart the server)" : ""}`);
    return kind === "json" ? r.json() : r.arrayBuffer();
  };
  const [pos, head, bin] = await Promise.all([
    get(CONFIG.positionsPath, "json"),
    get("/api/atlas", "json"),
    get("/api/atlas.bin", "bin"),
  ]);
  positions = pos;
  atlas = { header: head, xyz: new Int16Array(bin) };
  const unplaced = Object.entries(positions.groups_unplaced).filter(([, v]) => v.length);
  $("#brain-note").textContent =
    `Brain view: all ${head.n.toLocaleString()} neurons with a position in the FlyWire annotations are drawn; ` +
    `the ${positions.n_placed.toLocaleString()} simulated ones (of ${positions.n_neurons.toLocaleString()}; FlyWire v630 IDs ` +
    `unchanged in v783) can light up, the rest are anatomy only.` +
    (unplaced.length ? ` Unplaced in groups: ${unplaced.map(([g, v]) => `${g} ${v.length}`).join(", ")}.` : "") +
    " Up to 500 spiking neurons are sent per tick. Hover a neuron for its FlyWire annotation.";
  buildBrainView();
}

async function buildBrainView() {
  if (brain || !positions || !atlas || !state.brain) return;
  try {
    const [{ BrainView }, { detectQuality }] = await Promise.all([import("./brain3d.js"), import("./fly3d.js")]);
    if (brain) return;
    const groups = Object.fromEntries(Object.entries(state.brain.groups).map(([g, v]) => [g, v.ids]));
    const quality = params.get("quality") ?? detectQuality();
    brain = new BrainView($("#brain3d"), positions, atlas, groups, CONFIG, quality);
    perf.pointsDrawn = brain.nDrawn;
    $("#brain-msg").remove();
    state.takeSpikes(); // don't flash the backlog from before the view existed
    buildSelector();
    setSelection(selection);
    wireBrainHover();
    $("#label-l").hidden = $("#label-r").hidden = false;
  } catch (err) {
    $("#brain-msg").textContent = `3D view unavailable: ${err.message}. (three.js loads from cdn.jsdelivr.net.)`;
    perf.jsErrors.push(`brain3d: ${err.message}`);
  }
}

// ---- brain selection chips ("All", "Sugar", "Bitter", "MN9") ----
function buildSelector() {
  const seg = $("#brain-select");
  for (const opt of CONFIG.brainSelections) {
    if (opt.key !== "all" && !state.brain.groups[opt.key]) continue;
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("role", "radio");
    b.dataset.key = opt.key;
    b.textContent = opt.label;
    b.setAttribute("aria-checked", String(opt.key === selection));
    b.addEventListener("click", () => setSelection(opt.key));
    seg.appendChild(b);
  }
}

function setSelection(key) {
  selection = key;
  const n = brain?.setSelection(key) ?? 0;
  setText("#brain-count", selectionText(key, brain?.nSim ?? 0, brain?.nAtlas ?? 0, { [key]: n }));
  for (const b of document.querySelectorAll("#brain-select button")) {
    b.setAttribute("aria-checked", String(b.dataset.key === key));
  }
  moveIndicator($("#brain-select .seg-thumb"), $(`#brain-select button[data-key="${key}"]`), "thumb");
}

/** Slide a segment thumb / tab underline under `btn` (transform, plus width for the thumb). */
function moveIndicator(el, btn, kind) {
  if (!el || !btn) return;
  if (kind === "thumb") {
    el.style.width = `${btn.offsetWidth}px`;
    el.style.transform = `translateX(${btn.offsetLeft}px)`;
  } else {
    el.style.transform = `translateX(${btn.offsetLeft + 8}px) scaleX(${btn.offsetWidth - 16})`;
  }
}

// ---- hover: the FlyWire annotation of the neuron under the pointer ----
const neuronInfo = new Map();
const MEMBER = { mn9_primary: "MN9", sugar_grn: "sugar taste neuron", bitter_grn: "bitter taste neuron" };

function wireBrainHover() {
  const host = $("#brain3d");
  const tip = $("#neuron-tip");
  const ring = $("#hover-ring");
  let pending = null;
  let current = -1;
  const hide = () => {
    tip.hidden = true;
    ring.hidden = true;
    current = -1;
  };
  const show = async (hit) => {
    ring.hidden = false;
    ring.style.left = `${hit.x}px`;
    ring.style.top = `${hit.y}px`;
    if (hit.atlasIndex === current && !tip.hidden) return;
    current = hit.atlasIndex;
    let info = neuronInfo.get(hit.atlasIndex);
    if (!info) {
      try {
        info = await (await fetch(`/api/atlas/neuron/${hit.atlasIndex}`)).json();
      } catch {
        return;
      }
      neuronInfo.set(hit.atlasIndex, info);
      if (current !== hit.atlasIndex) return; // the pointer moved on meanwhile
    }
    $("#tip-title").textContent = neuronTitle(info);
    $("#tip-nt").textContent = info.top_nt ?? "transmitter unknown";
    $("#tip-id").textContent = `FlyWire ID ${info.root_id}`;
    const status = $("#tip-status");
    const c = CONFIG.brain.colors;
    if (info.simulated) {
      const act = brain.activity(info.root_id);
      const g = state.brain.groups;
      const member = Object.entries(MEMBER).find(([k]) => g[k]?.ids.includes(info.root_id))?.[1];
      status.textContent = `${act.firing ? "Firing" : act.stimulated ? "Stimulated" : "Simulated"}${member ? ` · ${member}` : ""}`;
      status.style.setProperty("--dot", act.firing ? c.firing : act.stimulated ? c.stimulated : c.resting);
    } else {
      status.textContent = "Not in the simulated circuit";
      status.style.setProperty("--dot", c.backdrop);
    }
    // Right-below the ring; flipped to the left near the right edge.
    const r = host.getBoundingClientRect();
    const w = 230;
    const left = hit.x + 18 + w > r.width ? hit.x - 18 - w : hit.x + 18;
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, Math.min(hit.y + 14, r.height - 110))}px`;
    tip.style.transformOrigin = left < hit.x ? "top right" : "top left";
    if (tip.hidden) {
      // Enter once (125 ms); moving on to the next neuron updates it instantly.
      tip.classList.add("entering");
      tip.hidden = false;
      requestAnimationFrame(() => tip.classList.remove("entering"));
    }
  };
  host.addEventListener("pointermove", (e) => {
    if (e.buttons || e.pointerType === "touch") return hide(); // dragging turns the brain
    const r = host.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    if (pending) cancelAnimationFrame(pending);
    pending = requestAnimationFrame(() => {
      pending = null;
      const hit = brain.pick(x, y);
      if (hit) show(hit);
      else hide();
    });
  });
  host.addEventListener("pointerleave", hide);
  host.addEventListener("pointerdown", hide);
}

function legend() {
  const c = CONFIG.brain.colors;
  $("#legend").innerHTML = [["resting", "Resting"], ["stimulated", "Stimulated"], ["firing", "Firing"]]
    .map(([k, label]) => `<li><i style="background:${c[k]}"></i>${label}</li>`)
    .join("");
}

/** L / R labels under each hemisphere, and the ring around a selected group. */
function updateBrainOverlay() {
  if (!brain || !brain.w) return;
  const sx = brain.sideScreenX();
  const sides = sideLabels(sx.left, sx.right);
  const place = (el, where) => {
    const v = `${where === "start" ? 22 : brain.w - 22}px`;
    if (el.style.left !== v) el.style.left = v;
  };
  place($("#label-l"), sides.left);
  place($("#label-r"), sides.right);
  const ring = $("#sel-ring");
  const c = brain.selectionCircle();
  ring.hidden = !c;
  if (c) {
    ring.style.left = `${c.x}px`;
    ring.style.top = `${c.y}px`;
    ring.style.width = ring.style.height = `${Math.max(28, 2 * c.r)}px`;
  }
}

// ---- fly camera tabs and the 1 mm scale bar ----
function wireFlyViews() {
  const tabs = document.querySelectorAll("#fly-views button");
  const line = $("#fly-views .tab-line");
  const select = (btn, instant = false) => {
    for (const b of tabs) b.setAttribute("aria-selected", String(b === btn));
    moveIndicator(line, btn, "line");
    fly.setView?.(btn.dataset.view, instant || reduceMotion);
  };
  for (const b of tabs) b.addEventListener("click", () => select(b));
  document.fonts?.ready.then(() => moveIndicator(line, document.querySelector('#fly-views [aria-selected="true"]'), "line"));
  moveIndicator(line, tabs[0], "line");
  return select;
}

let scaleW = 0;
function updateScaleBar() {
  const s = $("#scale");
  if (!fly.pxPerMm) {
    s.hidden = true;
    return;
  }
  s.hidden = false;
  const w = Math.round(fly.pxPerMm());
  if (Math.abs(w - scaleW) >= 1) {
    scaleW = w;
    $("#scale-line").style.width = `${w}px`;
  }
}

const STATE_WORD = { fainted: "Fainted", eating: "Eating", disgusted: "Disgusted", resting: "Resting", idle: "Idle" };

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
  const rules = state.brain?.game_rules;
  const fullSugar = state.brain?.stimuli?.sugar?.rate_hz;
  // Hunger scales the sugar drive (the one game -> brain link, Phase 5).
  const scaled = rules?.hunger_scales_sugar && sugarOn && fullSugar && tick.inputs_hz.sugar < 0.99 * fullSugar;
  let s;
  if (tick.game.fainted) {
    return `The fly fainted: it was starving (hunger at 100%) for ${rules?.faint_after_s ?? 30} s. ` +
      "Press Revive. Fainting is a game rule, not the connectome.";
  }
  if (!tick.game.eating && scaled && !bitterOn) {
    s = `The fly is full. Hunger sets the sugar signal to ${hz(tick.inputs_hz.sugar)} (of ${hz(fullSugar)}), ` +
      `too weak to drive MN9 over ${line} (MN9 ${hz(r.mn9_primary)}). No "full" rule: the brain just doesn't respond.`;
  } else if (tick.game.eating) {
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
  if (tick.game.dark ?? tick.game.light <= CONFIG.darkLevel) {
    s += " It's dark, so the fly rests. That part is a game rule: light isn't wired into this brain.";
  }
  return s;
}

function caption(s, tick) {
  const g = tick.game;
  switch (s) {
    case "eating":
      return `MN9 firing at ${g.mn9_rate_hz.toFixed(0)} Hz`;
    case "disgusted":
      return `Bitter neurons at ${tick.group_rates_hz.bitter_grn.toFixed(0)} Hz` +
        (g.mn9_rate_hz > 0 ? ` · MN9 ${g.mn9_rate_hz.toFixed(0)} Hz` : " · MN9 silent");
    case "resting":
      return `Resting in the dark · light ${Math.round(g.light * 100)}%`;
    case "fainted":
      return "Starved too long · press Revive";
    default:
      return "No taste input";
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
    setText("#mood-note", !game.mood_rules_active
      ? "Placeholder values: this server has no mood rules."
      : game.fainted ? "Fainted. Press Revive on the fly."
        : game.starving_s > 0
          ? `Starving: faints in ${Math.max(0, Math.ceil((state.brain?.game_rules?.faint_after_s ?? 30) - game.starving_s))} s unless it eats.`
          : "Hunger rises with time and falls only while MN9 says eating. Bitter-neuron spikes cost happiness; the dark restores energy.");
  }
  if (!tick) return;
  fly.setState(state.flyState, { sugar: tick.inputs_hz.sugar > 0, bitter: tick.inputs_hz.bitter > 0 },
    { mn9Hz: tick.game.mn9_rate_hz });
  const stage = $("#stage");
  if (stage.dataset.state !== state.flyState) stage.dataset.state = state.flyState;
  $("#revive").hidden = state.flyState !== "fainted";
  // Eating and disgust come from spikes; fainting and resting in the dark are game rules.
  const byRule = state.flyState === "fainted" || state.flyState === "resting";
  const tag = $("#state-tag");
  if (tag.dataset.rule !== String(byRule)) {
    tag.dataset.rule = String(byRule);
    tag.textContent = byRule ? "game rule" : "brain decides";
    tag.className = `tag ${byRule ? "game" : "brain"}`;
    tag.title = byRule ? "Fainting (starving too long) and resting in the dark are game rules"
      : "Eating is MN9 spikes; disgust is bitter-neuron spikes";
  }
  setText("#fly-state-word", STATE_WORD[state.flyState] ?? "Idle");
  setText("#fly-caption", caption(state.flyState, tick));
  setText("#gulps", String(state.gulps));
  setText("#gulps-word", state.gulps === 1 ? "gulp" : "gulps");
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
  const tick = state.lastTick;
  if (brain) {
    for (const ids of batches) brain.spike(ids);
    if (tick && tick.seq !== lastDrawnSeq) brain.setStimulated(stimulatedGroups(state.brain, tick.inputs_hz));
    perf.maxLit = Math.max(perf.maxLit, brain.render(source.paused === true));
    updateBrainOverlay();
  }
  if (tick && tick.seq !== lastDrawnSeq) {
    lastDrawnSeq = tick.seq;
    perf.ticksDrawn += 1;
    perf.tickAges.push(Date.now() - tick.server_time_ms);
    if (perf.tickAges.length > 400) perf.tickAges.shift();
  }
  fly.render(now);
  updateScaleBar();
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

$("#revive").addEventListener("click", () => source.send({ type: "revive" }));

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
      flyModel: fly.constructor?.name ?? "2d",
      atlasNeurons: brain?.nAtlas ?? 0,
      simNeurons: brain?.nSim ?? 0,
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
const selectView = wireFlyViews();

/** flybody model -> simple 3D fly -> 2D fly, whichever loads first in that order. */
async function loadFly() {
  const quality = params.get("quality") ?? CONFIG.fly3d.quality;
  const el = $("#fly");
  const put = (f) => {
    el.innerHTML = "";
    return f();
  };
  try {
    const { loadFlyModel, FlyModel3D } = await import("./fly_model3d.js");
    const { detectQuality } = await import("./fly3d.js");
    const q = quality === "high" || quality === "low" ? quality : detectQuality();
    const gltf = await loadFlyModel(q);
    fly = put(() => new FlyModel3D(el, gltf, CONFIG, q));
    selectView(document.querySelector('#fly-views [aria-selected="true"]'), true);
    return;
  } catch (err) {
    console.warn(`flybody model unavailable (${err.message}); trying the simple 3D fly`);
  }
  document.querySelector("#fly-views").hidden = true; // views need the model
  try {
    const { Fly3D } = await import("./fly3d.js");
    fly = put(() => new Fly3D(el, CONFIG, quality));
  } catch (err) {
    console.warn(`3D fly unavailable, showing the 2D fly: ${err.message}`);
  }
}
loadFly();
loadPositions().catch((err) => {
  $("#brain-msg").textContent = `No neuron positions: ${err.message}`;
  perf.jsErrors.push(`positions: ${err.message}`);
});
source.start(onMessage, setConn);
requestAnimationFrame(frame);

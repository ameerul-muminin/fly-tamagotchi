// Pure dashboard state: turns server messages (reports/MESSAGE_FORMAT.md) into what the
// page draws. No DOM here, so it runs in Node tests on the recorded sample.

import { CONFIG } from "./config.js";

/** Raw fly state for one tick, before the hold time is applied. */
export function deriveFlyState(tick, config = CONFIG) {
  const g = tick.game;
  const bitterHz = tick.group_rates_hz?.bitter_grn ?? 0;
  const tests = {
    eating: g.eating === true,
    disgusted: bitterHz >= config.disgustBitterHz,
    resting: g.light <= config.darkLevel,
    idle: true,
  };
  return config.statePriority.find((s) => tests[s]) ?? "idle";
}

export class DashboardState {
  constructor(config = CONFIG) {
    this.config = config;
    this.brain = null;          // hello.brain
    this.groupOf = new Map();   // neuron ID string -> color group
    this.clearSession();
    this.stats = { ticks: 0, lost: 0, errors: [], resets: 0 };
  }

  /** Forget the time series (on hello, reset_brain or when t_ms jumps backwards). */
  clearSession() {
    this.series = Object.fromEntries(this.config.chartSeries.map((s) => [s.group, []]));
    this.inputs = [];           // [{t, sugar, bitter}] Poisson drive per tick
    this.lastTick = null;
    this.game = null;
    this.flyState = null;
    this.pending = null;        // {state, since} candidate state waiting for the hold time
    this.statesSeen = new Set();
    this.spikeQueue = [];       // spiking ID lists not yet drawn by the 3D view
  }

  /** Apply one server message. Returns the message type. */
  apply(msg) {
    switch (msg.type) {
      case "hello":
        this.onHello(msg);
        break;
      case "tick":
        this.onTick(msg);
        break;
      case "ack":
        if (msg.event === "reset_brain") {
          this.stats.resets += 1;
          this.clearSession();
        }
        break;
      case "error":
        this.stats.errors.push(msg.error);
        break;
      default:
        break;
    }
    return msg.type;
  }

  onHello(msg) {
    this.brain = msg.brain;
    this.groupOf = new Map();
    const groups = msg.brain.groups;
    // Lowest priority first so higher-priority groups overwrite.
    for (const g of [...this.config.colorPriority].reverse()) {
      for (const id of groups[g]?.ids ?? []) this.groupOf.set(id, g);
    }
    this.clearSession();
    this.game = msg.game;
    this.lastSeq = null;
  }

  onTick(tick) {
    if (this.lastTick && tick.t_ms < this.lastTick.t_ms) this.clearSession();
    if (this.lastSeq != null && tick.seq > this.lastSeq + 1) {
      this.stats.lost += tick.seq - this.lastSeq - 1;
    }
    this.lastSeq = tick.seq;
    this.stats.ticks += 1;
    this.lastTick = tick;
    this.game = tick.game;

    const t = tick.t_ms;
    const cutoff = t - this.config.chartWindowMs;
    for (const { group } of this.config.chartSeries) {
      const s = this.series[group];
      s.push({ t, hz: tick.group_rates_hz[group] ?? 0 });
      while (s.length && s[0].t < cutoff) s.shift();
    }
    this.inputs.push({ t, sugar: tick.inputs_hz.sugar ?? 0, bitter: tick.inputs_hz.bitter ?? 0 });
    while (this.inputs.length && this.inputs[0].t < cutoff) this.inputs.shift();

    this.spikeQueue.push(tick.spiking_ids);
    this.updateFlyState(deriveFlyState(tick, this.config), t);
  }

  updateFlyState(raw, t) {
    if (this.flyState === null) {
      this.flyState = raw;
    } else if (raw === this.flyState) {
      this.pending = null;
    } else if (!this.pending || this.pending.state !== raw) {
      this.pending = { state: raw, since: t };
    }
    if (this.pending && t - this.pending.since >= this.config.stateHoldMs) {
      this.flyState = this.pending.state;
      this.pending = null;
    }
    this.statesSeen.add(this.flyState);
  }

  /** Spiking ID lists received since the last call (the 3D view flashes them). */
  takeSpikes() {
    const q = this.spikeQueue;
    this.spikeQueue = [];
    return q;
  }

  /** Color group of a neuron ID ("other" if it is in no highlighted group). */
  colorGroup(id) {
    return this.groupOf.get(id) ?? "other";
  }
}

// "Hear the brain": spikes become sound, the way an electrophysiology rig plays a
// recording electrode through a speaker. Every sound comes from spikes in a tick
// (reports/MESSAGE_FORMAT.md); a silent brain is a silent speaker.
//
// planTick() is pure (tested in Node); BrainSound plays its plan with WebAudio.

import { CONFIG } from "./config.js";

/**
 * What to play for one tick.
 * @returns {{mn9: number, sugar: number, bitter: number, other: number, cue: "gulp"|"yuck"|null}}
 */
export function planTick(tick, prevFlyState, flyState, config = CONFIG) {
  const s = config.sound;
  const cap = s.maxPerTick;
  const n = tick.group_counts ?? {};
  const sugar = n.sugar_grn ?? 0;
  const bitter = n.bitter_grn ?? 0;
  const mn9 = n.mn9_primary ?? 0;
  // Spikes outside the highlighted groups (mn9 includes mn9_primary, so count it once).
  const other = Math.max(0, (tick.total_spikes ?? 0) - sugar - bitter - (n.mn9 ?? mn9));
  let cue = null;
  if (flyState !== prevFlyState) {
    if (flyState === "eating") cue = "gulp";
    else if (flyState === "disgusted") cue = "yuck";
  }
  return {
    mn9: Math.min(cap.mn9, mn9),
    sugar: Math.min(cap.sugar, Math.ceil(sugar / s.groupSpikesPerNote)),
    bitter: Math.min(cap.bitter, Math.ceil(bitter / s.groupSpikesPerNote)),
    other: Math.min(cap.other, Math.round(s.otherClickScale * Math.sqrt(other))),
    cue,
  };
}

const SUGAR_NOTES = [1318.5, 1568.0, 1760.0, 2093.0, 2349.3]; // E6 G6 A6 C7 D7 (pentatonic)

export class BrainSound {
  constructor(config = CONFIG) {
    this.config = config;
    this.ctx = null;
    this.on = false;
    this.prevFlyState = null;
  }

  /** Must run inside a user gesture (browsers block audio until then). */
  async enable() {
    if (!this.ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new Ctx();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.config.sound.volume;
      const comp = this.ctx.createDynamicsCompressor();
      this.master.connect(comp).connect(this.ctx.destination);
      // 5 ms of white noise for the background clicks.
      const len = Math.round(this.ctx.sampleRate * 0.005);
      this.noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
      const d = this.noise.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len);
    }
    await this.ctx.resume();
    this.on = true;
  }

  disable() {
    this.on = false;
    this.ctx?.suspend();
  }

  /** Schedule the sounds for one tick, spread over the next tick window. */
  play(tick, flyState) {
    const prev = this.prevFlyState;
    this.prevFlyState = flyState;
    if (!this.on || !this.ctx) return;
    const plan = planTick(tick, prev, flyState, this.config);
    const t0 = this.ctx.currentTime + this.config.sound.scheduleAheadSec;
    const win = (tick.window_ms ?? 50) / 1000;
    const at = () => t0 + Math.random() * win;
    for (let i = 0; i < plan.other; i++) this.click(at());
    for (let i = 0; i < plan.sugar; i++) this.sugarNote(at(), tick.group_rates_hz?.sugar_grn ?? 0);
    for (let i = 0; i < plan.bitter; i++) this.bitterBuzz(at());
    for (let i = 0; i < plan.mn9; i++) this.mn9Thump(at());
    if (plan.cue === "gulp") this.gulp(t0);
    if (plan.cue === "yuck") this.yuck(t0);
  }

  env(t, peak, attack, decay) {
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
    g.connect(this.master);
    return g;
  }

  osc(type, freq, t, dur, out) {
    const o = this.ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    o.connect(out);
    o.start(t);
    o.stop(t + dur + 0.02);
    return o;
  }

  /** Any other neuron: a soft click, like spikes on an audio monitor. */
  click(t) {
    const src = this.ctx.createBufferSource();
    src.buffer = this.noise;
    const bp = this.ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = 2500 + Math.random() * 2500;
    bp.Q.value = 1.2;
    src.connect(bp).connect(this.env(t, 0.25, 0.001, 0.01));
    src.start(t);
  }

  /** Sugar neurons: a bright pluck; higher group rate -> higher note. */
  sugarNote(t, rateHz) {
    const i = Math.min(SUGAR_NOTES.length - 1, Math.floor(rateHz / 40));
    const f = SUGAR_NOTES[Math.max(0, i - Math.floor(Math.random() * 2))];
    this.osc("triangle", f, t, 0.08, this.env(t, 0.12, 0.002, 0.08));
  }

  /** Bitter neurons: a low, rough buzz. */
  bitterBuzz(t) {
    const lp = this.ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.value = 900;
    lp.connect(this.env(t, 0.12, 0.004, 0.07));
    this.osc("sawtooth", 150 + Math.random() * 30, t, 0.08, lp);
    this.osc("sawtooth", 158 + Math.random() * 30, t, 0.08, lp);
  }

  /** MN9 (the feeding motor neuron): a deep thump per spike, the pump you hear. */
  mn9Thump(t) {
    const g = this.env(t, 0.5, 0.002, 0.09);
    const o = this.osc("sine", 140, t, 0.1, g);
    o.frequency.exponentialRampToValueAtTime(55, t + 0.09);
  }

  /** Eating starts: a gulp (a falling sweep through a closing filter). */
  gulp(t) {
    const lp = this.ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(2200, t);
    lp.frequency.exponentialRampToValueAtTime(300, t + 0.18);
    lp.connect(this.env(t, 0.45, 0.01, 0.2));
    const o = this.osc("triangle", 520, t, 0.22, lp);
    o.frequency.exponentialRampToValueAtTime(160, t + 0.2);
  }

  /** Disgust starts: a dissonant "blech". */
  yuck(t) {
    const g = this.env(t, 0.3, 0.01, 0.3);
    for (const f of [220, 233, 311]) {
      const o = this.osc("sawtooth", f, t, 0.32, g);
      o.frequency.exponentialRampToValueAtTime(f * 0.7, t + 0.3);
    }
  }
}

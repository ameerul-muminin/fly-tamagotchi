// Rolling line chart of group firing rates (Hz) over simulated time, on a canvas.
// Bands under the plot show when the sugar / bitter inputs were driven.

import { CONFIG } from "./config.js";

const PAD = { l: 40, r: 84, t: 10, b: 34 };
const BAND_H = 5;

export class ActivityChart {
  constructor(canvas, tooltip, config = CONFIG) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.tooltip = tooltip;
    this.config = config;
    this.hoverX = null;
    this.dirty = true;
    this.drawnSeq = null;
    this.points = 0;
    canvas.addEventListener("pointermove", (e) => {
      const r = canvas.getBoundingClientRect();
      this.hoverX = e.clientX - r.left;
      this.dirty = true;
    });
    canvas.addEventListener("pointerleave", () => {
      this.hoverX = null;
      tooltip.hidden = true;
      this.dirty = true;
    });
    addEventListener("resize", () => (this.dirty = true));
  }

  /** Theme colors, read from CSS once. */
  get theme() {
    if (!this._theme) {
      const css = getComputedStyle(document.documentElement);
      const v = (name) => css.getPropertyValue(name).trim();
      this._theme = { ink: v("--ink"), muted: v("--ink-muted"), grid: v("--grid") };
    }
    return this._theme;
  }

  /** Redraw only when a new tick arrived, the pointer moved or the size changed. */
  update(state) {
    const seq = state.lastTick?.seq ?? null;
    if (this.dirty || seq !== this.drawnSeq || state.series[this.config.chartSeries[0].group].length === 0) {
      this.dirty = false;
      this.drawnSeq = seq;
      this.points = this.draw(state);
    }
    return this.points;
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const { width, height } = this.canvas.getBoundingClientRect();
    if (this.canvas.width !== Math.round(width * dpr) || this.canvas.height !== Math.round(height * dpr)) {
      this.canvas.width = Math.round(width * dpr);
      this.canvas.height = Math.round(height * dpr);
    }
    this.w = width;
    this.h = height;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  /** Draw the series held by a DashboardState. Returns the number of points drawn. */
  draw(state) {
    this.resize();
    const { ctx, w, h, config } = this;
    const { muted: ink, grid, ink: strongInk } = this.theme;
    ctx.clearRect(0, 0, w, h);

    const tEnd = state.lastTick?.t_ms ?? config.chartWindowMs;
    const tStart = tEnd - config.chartWindowMs;
    const plotW = w - PAD.l - PAD.r;
    const plotH = h - PAD.t - PAD.b - 2 * (BAND_H + 3);
    const x = (t) => PAD.l + ((t - tStart) / config.chartWindowMs) * plotW;
    const y = (hz) => PAD.t + plotH - (Math.min(hz, config.chartMaxHz) / config.chartMaxHz) * plotH;

    // grid + y labels
    ctx.font = "12px 'Atkinson Hyperlegible', system-ui, sans-serif";
    ctx.fillStyle = ink;
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let hz = 0; hz <= config.chartMaxHz; hz += 50) {
      ctx.beginPath();
      ctx.moveTo(PAD.l, y(hz) + 0.5);
      ctx.lineTo(PAD.l + plotW, y(hz) + 0.5);
      ctx.stroke();
      ctx.fillText(`${hz}`, PAD.l - 6, y(hz));
    }
    ctx.save();
    ctx.translate(11, PAD.t + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText("spikes/s per neuron", 0, 0);
    ctx.restore();

    // stimulus bands
    const bandTop = PAD.t + plotH + 6;
    const bands = [["sugar", "sugar_grn"], ["bitter", "bitter_grn"]];
    bands.forEach(([stim, group], k) => {
      ctx.fillStyle = config.colors[group];
      const yb = bandTop + k * (BAND_H + 3);
      for (let i = 0; i < state.inputs.length; i++) {
        const p = state.inputs[i];
        if (p[stim] > 0) {
          const t0 = p.t - (state.lastTick?.window_ms ?? 50);
          ctx.fillRect(x(Math.max(t0, tStart)), yb, Math.max(1, x(p.t) - x(Math.max(t0, tStart))), BAND_H);
        }
      }
    });
    ctx.fillStyle = ink;
    ctx.textAlign = "left";
    ctx.fillText("input on", PAD.l + plotW + 8, bandTop + BAND_H);

    // x labels: seconds of simulated time
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const first = Math.ceil(tStart / 2000) * 2000;
    for (let t = Math.max(0, first); t <= tEnd; t += 2000) {
      ctx.fillText(`${(t / 1000).toFixed(0)} s`, x(t), h - 14);
    }

    // lines + direct labels at the right end
    let points = 0;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    const labels = [];
    for (const { group, label } of config.chartSeries) {
      const s = state.series[group];
      if (!s.length) continue;
      ctx.strokeStyle = config.colors[group];
      ctx.beginPath();
      s.forEach((p, i) => (i ? ctx.lineTo(x(p.t), y(p.hz)) : ctx.moveTo(x(p.t), y(p.hz))));
      ctx.stroke();
      points += s.length;
      labels.push({ group, label, y: y(s[s.length - 1].hz) });
    }
    // Spread labels 13 px apart, keeping them inside the plot area.
    labels.sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 13);
    const bottom = PAD.t + plotH - 4;
    for (let i = labels.length - 1; i >= 0; i--) {
      const limit = i === labels.length - 1 ? bottom : labels[i + 1].y - 13;
      labels[i].y = Math.min(labels[i].y, limit);
    }
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    for (const l of labels) {
      ctx.fillStyle = config.colors[l.group];
      ctx.fillRect(PAD.l + plotW + 6, l.y - 1, 8, 2);
      ctx.fillStyle = strongInk;
      ctx.fillText(l.label, PAD.l + plotW + 18, l.y);
    }

    this.drawHover(state, x, y, tStart, plotW, plotH);
    return points;
  }

  drawHover(state, x, y, tStart, plotW, plotH) {
    const { ctx, config, hoverX, tooltip } = this;
    if (hoverX == null || hoverX < PAD.l || hoverX > PAD.l + plotW) {
      tooltip.hidden = true;
      return;
    }
    const t = tStart + ((hoverX - PAD.l) / plotW) * config.chartWindowMs;
    const rows = [];
    for (const { group, label } of config.chartSeries) {
      const s = state.series[group];
      if (!s.length) continue;
      let best = s[0];
      for (const p of s) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
      rows.push({ group, label, p: best });
    }
    if (!rows.length) return;
    const xt = x(rows[0].p.t);
    ctx.strokeStyle = this.theme.muted;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(xt + 0.5, PAD.t);
    ctx.lineTo(xt + 0.5, PAD.t + plotH);
    ctx.stroke();
    for (const r of rows) {
      ctx.fillStyle = config.colors[r.group];
      ctx.beginPath();
      ctx.arc(xt, y(r.p.hz), 4, 0, 2 * Math.PI);
      ctx.fill();
    }
    tooltip.hidden = false;
    tooltip.style.left = `${Math.min(xt + 12, this.w - 170)}px`;
    tooltip.innerHTML =
      `<b>t = ${(rows[0].p.t / 1000).toFixed(2)} s</b>` +
      rows
        .map((r) => `<div><i style="background:${config.colors[r.group]}"></i>${r.label}: ${r.p.hz.toFixed(1)} Hz</div>`)
        .join("");
  }
}

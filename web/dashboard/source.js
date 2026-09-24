// Where messages come from: the live server WebSocket, or a recorded session
// (web/dashboard/samples/*.jsonl, written by `python -m server.record_session`).

import { CONFIG } from "./config.js";

/** Parse a recorded session: keep what the dashboard received, in order. */
export function parseRecording(text) {
  return text
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l))
    .filter((l) => l.src === "dashboard");
}

export class LiveSource {
  constructor(url) {
    this.kind = "live";
    this.url = url;
    this.ws = null;
    this.stopped = false;
  }

  start(onMessage, onStatus) {
    const open = () => {
      if (this.stopped) return;
      onStatus("connecting");
      const ws = new WebSocket(this.url);
      this.ws = ws;
      ws.onopen = () => onStatus("live");
      ws.onmessage = (e) => onMessage(JSON.parse(e.data));
      ws.onclose = () => {
        onStatus("disconnected");
        setTimeout(open, CONFIG.reconnectMs);
      };
    };
    open();
  }

  send(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }
}

export class ReplaySource {
  /**
   * @param {string} url recorded .jsonl file
   * @param {number} speed playback speed (1 = as recorded)
   * @param {boolean} loop start over at the end
   */
  constructor(url, speed = 1, loop = false) {
    this.kind = "replay";
    this.url = url;
    this.speed = speed;
    this.loop = loop;
    this.done = false;
    this.paused = false;
    this.lines = [];
  }

  async start(onMessage, onStatus) {
    onStatus("loading replay");
    const res = await fetch(this.url);
    if (!res.ok) throw new Error(`replay ${this.url}: HTTP ${res.status}`);
    this.lines = parseRecording(await res.text());
    const play = () => {
      this.done = false;
      onStatus(`replay ×${this.speed}`);
      this.clock = 0; // recording time [ms]; only advances while not paused
      let last = performance.now();
      let i = 0;
      const step = () => {
        const now = performance.now();
        if (!this.paused) this.clock += (now - last) * this.speed;
        last = now;
        while (i < this.lines.length && this.lines[i].t_wall_ms <= this.clock) {
          onMessage(this.lines[i].msg);
          i += 1;
        }
        if (i < this.lines.length) {
          setTimeout(step, 10);
        } else if (this.loop) {
          setTimeout(play, 1000);
        } else {
          this.done = true;
          onStatus("replay finished");
        }
      };
      step();
    };
    play();
  }

  /** Freeze or continue playback (used for screenshots). */
  setPaused(paused) {
    this.paused = paused;
  }

  send(msg) {
    // A recording cannot be steered; the reset button only clears the charts.
    return msg;
  }
}

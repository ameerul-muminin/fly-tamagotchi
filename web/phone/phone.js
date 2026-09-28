// Browser glue for the phone page: DOM, WebSocket, DeviceMotion, camera, vibration.
// All decisions about what to send live in controller.js.

import { backoffDelay, createController, DEFAULTS } from "./controller.js";

const $ = (id) => document.getElementById(id);
const now = () => performance.now();

async function loadConfig() {
  try {
    const r = await fetch("/api/phone-config", { cache: "no-store" });
    if (r.ok) return await r.json();
  } catch { /* offline or old server: use the defaults */ }
  return { ...DEFAULTS };
}

// ------------------------------------------------------------------ socket
let ws = null;
let attempt = 0;

function send(msg) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(msg));
  return true;
}

function setConn(state, text) {
  $("conn").dataset.state = state;
  $("conn-text").textContent = text;
}

function connect(ctl) {
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/phone`;
  setConn("connecting", attempt ? `reconnecting (${attempt})` : "connecting");
  ws = new WebSocket(url);
  ws.onopen = () => { attempt = 0; setConn("open", "connected"); ctl.ping(); };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    ctl.handle(msg);
    render(ctl);
  };
  ws.onclose = () => {
    ctl.disconnected();
    const wait = backoffDelay(attempt++, ctl.config);
    setConn("closed", `offline, retry in ${(wait / 1000).toFixed(1)} s`);
    setTimeout(() => connect(ctl), wait);
  };
}

// ------------------------------------------------------------------ feedback
function flash() {
  document.body.classList.add("flash");
  setTimeout(() => document.body.classList.remove("flash"), 260);
}

function vibrate(pattern) {
  let done = false;
  try { done = typeof navigator.vibrate === "function" && navigator.vibrate(pattern); } catch { /* ignore */ }
  if (!done) $("haptic").click(); // iOS 18+ haptic tick; no Vibration API on iOS Safari
  flash();
}

// ------------------------------------------------------------------ rendering
const pct = (v) => (v == null ? "0%" : `${Math.round(Math.min(1, Math.max(0, v)) * 100)}%`);

function render(ctl) {
  const v = ctl.state.view;
  if (!v) return;
  $("m-hunger").style.width = pct(v.hunger);
  $("m-happiness").style.width = pct(v.happiness);
  $("m-energy").style.width = pct(v.energy);
  $("mood-note").hidden = !v.moodPlaceholder;
  $("mn9").textContent = `MN9 ${Math.round(v.mn9Hz)} Hz`;
  const stims = [];
  if (v.sugarLeftMs > 0) stims.push(`sugar ${(v.sugarLeftMs / 1000).toFixed(1)} s`);
  if (v.bitterLeftMs > 0) stims.push(`bitter ${(v.bitterLeftMs / 1000).toFixed(1)} s`);
  $("stims").textContent = stims.length ? stims.join(" + ") : "no taste";
  let line = "Not eating";
  let mood = "idle";
  if (v.fainted) { line = "Fainted! Revive it on the laptop"; mood = "fainted"; }
  else if (v.eating) { line = "Eating!"; mood = "eating"; }
  else if (v.sugarLeftMs > 0 && v.bitterLeftMs > 0) line = "Tastes bitter… not eating";
  else if (v.bitterLeftMs > 0) line = "Yuck, bitter";
  else if (v.dark) { line = "Resting in the dark"; mood = "dark"; }
  else if (v.hunger != null && v.hunger >= 0.8) line = "Hungry! Tap for sugar";
  $("fly-line").textContent = line;
  $("fly-face").dataset.mood = mood;
  const rtt = ctl.state.rttMs;
  if (rtt != null && ws?.readyState === WebSocket.OPEN) $("conn-text").textContent = `connected · ${Math.round(rtt)} ms`;
}

// ------------------------------------------------------------------ sensors
let motionOn = false;

function startMotion(ctl) {
  if (motionOn) return; // "Try again" / "Restart camera" must not add a second listener
  motionOn = true;
  window.addEventListener("devicemotion", (e) => {
    const fired = ctl.motion({ acc: e.acceleration, accG: e.accelerationIncludingGravity, t: now() });
    if (fired) {
      const card = $("shake-card");
      card.classList.remove("fired");
      void card.offsetWidth; // restart the animation
      card.classList.add("fired");
      $("shake-state").textContent = "bitter!";
      setTimeout(() => { $("shake-state").textContent = "on"; }, 1200);
    }
  });
  $("shake-state").textContent = "on";
}

async function startCamera(ctl) {
  const c = ctl.config;
  const video = $("cam");
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: c.camera_facing, width: { ideal: 320 }, height: { ideal: 240 } },
    audio: false,
  });
  video.srcObject = stream;
  video.classList.add("on");
  // Don't wait for play(): its promise can stay pending (seen when the track ends), and
  // the sampling loop below only reads frames once the video has data anyway.
  video.play().catch(() => {});
  const [track] = stream.getVideoTracks();
  track?.addEventListener("ended", () => {
    // iOS stops the camera when the page goes to the background.
    clearInterval(timer);
    video.classList.remove("on");
    $("light-value").textContent = "stopped";
    $("enable").disabled = false;
    $("enable").textContent = "Restart camera";
  });
  const canvas = document.createElement("canvas");
  canvas.width = c.camera_width;
  canvas.height = c.camera_height;
  const g = canvas.getContext("2d", { willReadFrequently: true });
  const timer = setInterval(() => {
    if (document.hidden || video.readyState < 2) return;
    g.drawImage(video, 0, 0, canvas.width, canvas.height);
    const level = ctl.frame(g.getImageData(0, 0, canvas.width, canvas.height).data);
    $("light-value").textContent = level < c.dark_below ? `dark ${level.toFixed(2)}` : level.toFixed(2);
    $("light-fill").style.width = pct(level);
  }, 1000 / c.camera_sample_hz);
  return stream;
}

async function enableSensors(ctl) {
  const btn = $("enable");
  const notes = [];
  btn.disabled = true;
  // iOS: requestPermission must be the first call inside the tap handler, and the camera
  // request starts in the same gesture, before any await.
  const DM = window.DeviceMotionEvent;
  const motionAsk = DM && typeof DM.requestPermission === "function"
    ? DM.requestPermission() : Promise.resolve(DM ? "granted" : "unsupported");
  const camera = navigator.mediaDevices?.getUserMedia
    ? startCamera(ctl) : Promise.reject(new Error("camera API missing (needs HTTPS)"));
  navigator.wakeLock?.request("screen").catch(() => {});

  const [motion, cam] = await Promise.allSettled([motionAsk, camera]);
  if (motion.status === "fulfilled" && motion.value === "granted") startMotion(ctl);
  else {
    $("shake-state").textContent = "blocked";
    notes.push(`Shake: ${motion.status === "fulfilled" ? motion.value : motion.reason?.message ?? "error"}.`);
  }
  if (cam.status === "rejected") {
    $("light-value").textContent = "blocked";
    notes.push(`Camera: ${cam.reason?.message ?? cam.reason}.`);
  }
  if (notes.length) {
    $("sensor-note").textContent = notes.join(" ");
    $("sensor-note").hidden = false;
    btn.disabled = false;
    btn.textContent = "Try again";
  } else {
    btn.textContent = "Shake + camera on";
  }
}

// ------------------------------------------------------------------ start
async function main() {
  const config = await loadConfig();
  const ctl = createController({ send, vibrate, now, config });
  window.flyController = ctl; // for debugging from the console

  const tap = $("tap");
  tap.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    ctl.tap();
    const r = tap.getBoundingClientRect();
    const dot = document.createElement("span");
    dot.className = "ripple";
    dot.style.left = `${e.clientX - r.left}px`;
    dot.style.top = `${e.clientY - r.top}px`;
    tap.appendChild(dot);
    setTimeout(() => dot.remove(), 600);
  });
  $("enable").addEventListener("click", () => enableSensors(ctl));
  $("secure-note").hidden = window.isSecureContext;

  connect(ctl);
  setInterval(() => ctl.ping(), 3000);
}

main();

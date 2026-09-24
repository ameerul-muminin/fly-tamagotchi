// Browser smoke test for the phone page in a real (headless) Chromium browser: Edge or Chrome.
// Not part of pytest (needs a browser). Usage:
//   node tests/js/browser_smoke.mjs <server base URL> <browser exe> <output dir>
//
// Drives the actual page over the DevTools protocol at iPhone size: a real pointer tap on the
// sugar zone, a click on "Enable shake + camera" (fake camera device), synthetic devicemotion
// events, and a screenshot. Fails on any JS exception or console error.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [base = "http://127.0.0.1:8000", exe, outDir = "."] = process.argv.slice(2);
const port = 9333;
mkdirSync(outDir, { recursive: true });
const browser = spawn(exe, [
  "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${join(outDir, "profile")}`,
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--no-first-run",
  "--window-size=390,844", "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = [];
const check = (name, ok, detail = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? ` (${detail})` : ""}`); };

let target;
for (let i = 0; i < 50 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); }
  catch { await sleep(200); }
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
let id = 0;
const pending = new Map();
const errors = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text);
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map((a) => a.value ?? a.description).join(" "));
};
const cdp = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => (await cdp("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;
const text = (elId) => evaluate(`document.getElementById(${JSON.stringify(elId)}).textContent`);
const click = async (elId) => {
  const [x, y] = await evaluate(`(() => { const el = document.getElementById(${JSON.stringify(elId)}); el.scrollIntoView({ block: "center" }); const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
  await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
};

await cdp("Runtime.enable");
await cdp("Page.enable");
await cdp("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
// Record vibrations (desktop Chromium ignores vibrate without a device).
await cdp("Page.addScriptToEvaluateOnNewDocument", { source: "window.__vib = []; navigator.vibrate = (p) => (window.__vib.push(p), true);" });
// Mock camera: a canvas stream whose color the test sets (headless Edge's fake capture
// device ends its track immediately, so it can't be used).
await cdp("Page.addScriptToEvaluateOnNewDocument", { source: `
  window.__camColor = "#e6e1d2";
  navigator.mediaDevices.getUserMedia = async () => {
    const c = document.createElement("canvas"); c.width = 64; c.height = 48;
    const g = c.getContext("2d");
    setInterval(() => { g.fillStyle = window.__camColor; g.fillRect(0, 0, 64, 48); }, 40);
    return c.captureStream(25);
  };` });
await cdp("Page.navigate", { url: `${base}/phone/` });
await sleep(1500);

check("page connects to the server", /connected/.test(await text("conn-text")), await text("conn-text"));
check("status shown (mood bars filled)", (await evaluate(`document.getElementById("m-energy").style.width`)) === "100%");
check("mood marked as placeholder", (await evaluate(`document.getElementById("mood-note").hidden`)) === false);

await click("tap");
await sleep(800);
const eatLine = await text("fly-line");
check("pointer tap -> fly eating on the phone", eatLine === "Eating!", `${eatLine}, ${await text("mn9")}, ${await text("stims")}`);
check("vibrate called on the eating onset", (await evaluate("window.__vib.length")) === 1, JSON.stringify(await evaluate("window.__vib")));
await cdp("Page.captureScreenshot", { format: "png" }).then((r) => writeFileSync(join(outDir, "phone_eating.png"), Buffer.from(r.result.data, "base64")));
await sleep(2500);

await click("enable");
await sleep(2000);
check("enable button: shake on", (await text("shake-state")) === "on", await text("shake-state"));
const bright = await text("light-value");
check("bright mock camera -> light level >= 0.8", Number(bright) >= 0.8, bright);
await evaluate(`window.__camColor = "#030303"`); // hand over the camera
await sleep(1200);
const dark = await text("light-value");
check("covered mock camera -> 'dark' level <= 0.05", /^dark /.test(dark) && Number(dark.slice(5)) <= 0.05, dark);
const serverLight = await evaluate("window.flyController.state.status.light"); // from the last server status
check("server status reports the dark level", serverLight <= 0.05, `status.light=${serverLight}; fly: ${await text("fly-line")}`);
await cdp("Page.captureScreenshot", { format: "png" }).then((r) => writeFileSync(join(outDir, "phone_dark.png"), Buffer.from(r.result.data, "base64")));
await evaluate(`window.__camColor = "#e6e1d2"`);

// Synthetic shake: 25 m/s^2 at 5 Hz, 60 samples/s for 0.7 s.
await evaluate(`(async () => {
  for (let i = 0; i <= 42; i++) {
    const x = 25 * Math.sin(2 * Math.PI * 5 * i / 60);
    window.dispatchEvent(new DeviceMotionEvent("devicemotion", {
      acceleration: { x, y: 0, z: 0 }, accelerationIncludingGravity: { x, y: 0, z: 9.81 }, interval: 16 }));
    await new Promise((r) => setTimeout(r, 16));
  }
})()`);
await sleep(700);
const stims = await text("stims");
check("shake -> bitter sent and shown on the phone", /bitter/.test(stims), `${stims}, ${await text("fly-line")}`);
await cdp("Page.captureScreenshot", { format: "png" }).then((r) => writeFileSync(join(outDir, "phone_bitter.png"), Buffer.from(r.result.data, "base64")));

check("no JS exceptions or console errors", errors.length === 0, errors.join(" | "));
ws.close();
browser.kill();
console.log(`${checks.filter(Boolean).length}/${checks.length} browser checks passed; screenshots in ${outDir}`);
process.exit(checks.every(Boolean) ? 0 : 1);

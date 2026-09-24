// "Connect a phone" panel: QR code and URL for the phone page (Phase 3 endpoints in
// server/web.py). The panel stays hidden when the server has no /api/phone-url, as in
// the replay-only app (server/dashboard.py create_replay_app).

import { CONFIG } from "./config.js";

const $ = (id) => document.getElementById(id);
const SOURCE_TEXT = {
  config: "from FLY_PUBLIC_URL / --public-url",
  ngrok: "ngrok tunnel (HTTPS)",
  lan: "this laptop's Wi-Fi address; the phone must be on the same network",
};

async function refresh() {
  let info;
  try {
    const res = await fetch("/api/phone-url", { cache: "no-store" });
    if (!res.ok) return;
    info = await res.json();
  } catch {
    return; // server restarting; the next refresh retries
  }
  $("phone-panel").hidden = false;
  $("phone-url").textContent = info.url;
  $("phone-source").textContent = `Source: ${SOURCE_TEXT[info.source] ?? info.source}`;
  $("phone-note").hidden = !info.note;
  $("phone-note").textContent = info.note ?? "";
  const src = `/api/qr.svg?u=${encodeURIComponent(info.url)}`;
  if ($("qr").getAttribute("src") !== src) $("qr").src = src;
  try {
    const health = await (await fetch("/health", { cache: "no-store" })).json();
    $("phone-count").textContent = health.clients.phone;
  } catch { /* ignore */ }
}

refresh();
setInterval(refresh, CONFIG.phoneLinkRefreshMs);

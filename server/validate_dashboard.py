"""Phase 4 validation: the dashboard renders in a real browser, from a recording and live.

Usage: python -m server.validate_dashboard [--chrome PATH] [--skip-live]

1. Replay: a brain-free app serves the page, /api/positions and the recorded sample
   (web/dashboard/samples/session.jsonl). Headless Chrome plays it back; we check the
   3D view drew points and flashed spikes, the chart has data, all four fly states
   appeared, and the page threw no errors. One screenshot per fly state goes to reports/.
2. Live: a real server (reduced brain) plus a scripted phone. We measure, inside the
   page, tick receive rate, lost ticks, frame rate and tick age, and press Reset.

Thresholds: server/config.py DASHBOARD_CHECKS (fixed before the first run).
Results: data/phase4_validation.json. Exit code 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
from websockets.asyncio.client import connect

from brain.config import DATA_DIR, PROJECT_ROOT
from server.config import DASHBOARD_CHECKS, RECORD_SCRIPT, SERVER
from server.dashboard import SAMPLE_PATH, create_replay_app
from server.fake_phone import spawn_server

RESULTS_PATH = DATA_DIR / "phase4_validation.json"
SHOTS_DIR = PROJECT_ROOT / "reports" / "phase4_screenshots"
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser",
]
REPLAY_PORT, LIVE_PORT, CDP_PORT = 8770, 8771, 9333


def find_chrome(explicit: str | None) -> str:
    for c in [explicit] if explicit else CHROME_CANDIDATES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    raise SystemExit("BLOCKED: no Chrome/Edge found; pass --chrome PATH")


class Cdp:
    """Minimal Chrome DevTools protocol client for one page."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.n = 0

    async def call(self, method: str, **params) -> dict:
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg["result"]

    async def eval(self, expr: str):
        r = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("text", "evaluate failed"))
        return r["result"].get("value")

    async def snapshot(self) -> dict | None:
        return await self.eval("window.__dash ? window.__dash.snapshot() : null")

    async def screenshot(self, path: Path) -> None:
        r = await self.call("Page.captureScreenshot", format="png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(r["data"]))


def start_chrome(chrome: str, profile: str) -> subprocess.Popen:
    return subprocess.Popen([
        chrome, "--headless=new", f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={profile}",
        "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--window-size=1400,950",
        "--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
        "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def page_ws_url(timeout_s: float = 20) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1) as r:
                pages = [p for p in json.load(r) if p["type"] == "page"]
                if pages:
                    return pages[0]["webSocketDebuggerUrl"]
        except OSError:
            pass
        time.sleep(0.3)
    raise RuntimeError("Chrome DevTools endpoint did not come up")


def serve_in_thread(app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    return server


async def open_page(cdp: Cdp, url: str) -> None:
    await cdp.call("Page.enable")
    await cdp.call("Runtime.enable")
    await cdp.call("Page.navigate", url=url)


async def blank_page_fps(cdp: Cdp) -> float:
    """Frame rate this browser gives an empty page (context for the fps check)."""
    await open_page(cdp, "data:text/html,<p>blank</p>")
    await asyncio.sleep(1.0)
    return await cdp.eval(
        "new Promise(res => { const t = []; let p = performance.now();"
        " const f = (n) => { t.push(n - p); p = n; if (t.length < 120) requestAnimationFrame(f);"
        " else { t.sort((a, b) => a - b); res(1000 / t[60]); } }; requestAnimationFrame(f); })")


async def replay_check(cdp: Cdp) -> dict:
    c = DASHBOARD_CHECKS
    sample_ticks = sum(1 for line in SAMPLE_PATH.read_text(encoding="utf-8").splitlines()
                       if '"type":"tick"' in line and '"src":"dashboard"' in line)
    await open_page(cdp, f"http://127.0.0.1:{REPLAY_PORT}/dashboard/"
                         f"?replay=samples/session.jsonl&speed={c.replay_speed}")
    shots: dict[str, str] = {}
    snap: dict | None = None
    deadline = time.time() + 120
    while time.time() < deadline:
        await asyncio.sleep(0.1)
        snap = await cdp.snapshot()
        if not snap:
            continue
        st = snap["flyDomState"]
        if st and st not in shots and snap["brainView"]:
            # Freeze playback (and the flash fade) so the shot shows this state,
            # wait for the CSS transitions, then continue.
            await cdp.eval("window.__dash.source.setPaused(true), true")
            await asyncio.sleep(0.5)
            path = SHOTS_DIR / f"replay_{st}.png"
            await cdp.screenshot(path)
            await cdp.eval("window.__dash.source.setPaused(false), true")
            shots[st] = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        if snap["replayDone"]:
            await asyncio.sleep(0.5)
            snap = await cdp.snapshot()
            break
    assert snap is not None, "page never exposed window.__dash"
    checks = {
        "every recorded tick applied": snap["ticks"] == sample_ticks,
        "3D view built": snap["brainView"] and snap["pointsDrawn"] > 0,
        "spiking neurons flashed": snap["flashedTotal"] > 0 and snap["maxLit"] > 0,
        "chart has data": snap["chartPoints"] > 0,
        "all four fly states shown": set(c.replay_states) <= set(snap["statesSeen"]),
        "fly SVG state matches state": snap["flyDomState"] == snap["flyState"],
        "mood bars filled": all(v for v in snap["mood"].values()),
        "no JS errors": len(snap["jsErrors"]) <= c.max_js_errors,
    }
    return {"snapshot": snap, "sample_ticks": sample_ticks, "screenshots": shots, "checks": checks}


async def drive_phone(url: str, seconds: float) -> None:
    """Send the recording script's phone events, looping, for `seconds`."""
    async with connect(f"{url}/ws/phone") as phone:
        await phone.recv()
        end = time.time() + seconds
        while time.time() < end:
            for _, secs, messages in RECORD_SCRIPT:
                for m in messages:
                    await phone.send(json.dumps(m))
                await asyncio.sleep(min(secs, max(0.0, end - time.time())))
                if time.time() >= end:
                    return


async def live_check(cdp: Cdp) -> dict:
    c = DASHBOARD_CHECKS
    await open_page(cdp, f"http://127.0.0.1:{LIVE_PORT}/dashboard/")
    deadline = time.time() + 30
    while time.time() < deadline:
        snap = await cdp.snapshot()
        if snap and snap["brainView"] and snap["ticks"] > 5:
            break
        await asyncio.sleep(0.2)
    # Measure from here: clear the in-page counters.
    await cdp.eval("(() => { const d = window.__dash; d.perf.frames.length = 0; d.perf.tickAges.length = 0;"
                   " d.perf.workMs.length = 0;"
                   " d.perf.firstTickWallMs = null; d.state.stats.ticks = 0; d.state.stats.lost = 0;"
                   " d.state.statesSeen.clear(); d.perf.jsErrors.length = 0; return true; })()")
    await drive_phone(f"ws://127.0.0.1:{LIVE_PORT}", c.live_seconds)
    snap = await cdp.snapshot()
    await cdp.screenshot(SHOTS_DIR / "live.png")

    # Reset button: the server acks and the page clears; t_ms restarts near 0.
    t_before = await cdp.eval("window.__dash.state.lastTick.t_ms")
    resets_before = await cdp.eval("window.__dash.state.stats.resets")
    await cdp.eval("document.querySelector('#reset').click(), true")
    await asyncio.sleep(1.0)
    resets_after = await cdp.eval("window.__dash.state.stats.resets")
    t_after = await cdp.eval("window.__dash.state.lastTick ? window.__dash.state.lastTick.t_ms : null")

    span_s = snap["tickWallSpanMs"] / 1000.0
    tick_rate = (snap["ticks"] - 1) / span_s if span_s > 0 else 0.0
    lost_frac = snap["lost"] / max(1, snap["ticks"] + snap["lost"])
    measured = {
        "tick_rate_hz": tick_rate,
        "lost_frac": lost_frac,
        "median_fps": snap["medianFps"],
        "median_frame_work_ms": snap["medianFrameWorkMs"],
        "p95_frame_work_ms": snap["p95FrameWorkMs"],
        "p95_tick_age_ms": snap["p95TickAgeMs"],
        "js_errors": snap["jsErrors"],
        "states_seen": snap["statesSeen"],
        "reset": {"t_before_ms": t_before, "t_after_ms": t_after,
                  "resets_before": resets_before, "resets_after": resets_after},
    }
    checks = {
        f"tick rate >= {c.min_tick_rate_frac} x {SERVER.broadcast_hz:g} Hz":
            tick_rate >= c.min_tick_rate_frac * SERVER.broadcast_hz,
        f"lost ticks <= {c.max_lost_frac:.0%}": lost_frac <= c.max_lost_frac,
        f"median fps >= {c.min_median_fps:g}": snap["medianFps"] >= c.min_median_fps,
        f"p95 tick age <= {c.max_p95_tick_age_ms:g} ms":
            snap["p95TickAgeMs"] is not None and snap["p95TickAgeMs"] <= c.max_p95_tick_age_ms,
        "no JS errors": len(snap["jsErrors"]) <= c.max_js_errors,
        "reset button restarts the brain": resets_after == resets_before + 1
            and t_after is not None and t_after < min(t_before, 1500),
    }
    return {"snapshot": snap, "measured": measured, "checks": checks}


async def run(chrome: str, skip_live: bool) -> dict:
    results: dict = {"thresholds": DASHBOARD_CHECKS.__dict__ | {"replay_states": list(DASHBOARD_CHECKS.replay_states)}}
    with tempfile.TemporaryDirectory(prefix="fly-chrome-") as profile:
        proc = start_chrome(chrome, profile)
        replay_srv = serve_in_thread(create_replay_app(), REPLAY_PORT)
        live_proc = None
        try:
            async with connect(page_ws_url(), max_size=None) as ws:
                cdp = Cdp(ws)
                results["blank_page_fps"] = await blank_page_fps(cdp)
                results["replay"] = await replay_check(cdp)
                if not skip_live:
                    live_proc = spawn_server(LIVE_PORT, "reduced")
                    results["live"] = await live_check(cdp)
        finally:
            replay_srv.should_exit = True
            if live_proc:
                live_proc.terminate()
                live_proc.wait(timeout=30)
            proc.terminate()
            proc.wait(timeout=30)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chrome", help="Chrome/Edge executable")
    ap.add_argument("--skip-live", action="store_true", help="replay check only")
    args = ap.parse_args()
    results = asyncio.run(run(find_chrome(args.chrome), args.skip_live))

    ok = True
    for part in ("replay", "live"):
        if part not in results:
            continue
        r = results[part]
        print(f"\n== {part} ==")
        if part == "replay":
            s = r["snapshot"]
            print(f"  ticks applied {s['ticks']}/{r['sample_ticks']}, points {s['pointsDrawn']}, "
                  f"max lit {s['maxLit']}, flashes {s['flashedTotal']}, chart points {s['chartPoints']}")
            print(f"  fly states seen: {', '.join(s['statesSeen'])}")
            print(f"  screenshots: {', '.join(r['screenshots'].values())}")
        else:
            m = r["measured"]
            print(f"  tick rate {m['tick_rate_hz']:.2f} Hz, lost {m['lost_frac']:.2%}, "
                  f"median fps {m['median_fps']:.1f} (blank page {results['blank_page_fps']:.1f}), "
                  f"p95 tick age {m['p95_tick_age_ms']:.1f} ms")
            print(f"  JS work per frame: median {m['median_frame_work_ms']:.1f} ms, "
                  f"p95 {m['p95_frame_work_ms']:.1f} ms (GPU time not included)")
            print(f"  fly states seen: {', '.join(m['states_seen'])}; reset: {m['reset']}")
        for name, passed in r["checks"].items():
            ok &= bool(passed)
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    RESULTS_PATH.write_text(json.dumps(results, indent=1, default=str))
    print(f"\nresults: {RESULTS_PATH}")
    print("ALL CHECKS PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

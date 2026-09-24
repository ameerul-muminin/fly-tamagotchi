"""Send fake phone events to the server and print the spike counts that come back.

Usage:
    python -m server.fake_phone --spawn          # start a server, run the script, stop it
    python -m server.fake_phone --url ws://127.0.0.1:8000   # use a running server

Connects as a phone and as a dashboard, then runs baseline -> sugar ->
sugar+bitter -> bitter -> stop. Every tick is labelled by the input rates the
server reports in it, not by wall-clock guesses. Exits 0 if MN9 counts change
as expected: up with sugar, down with bitter, back to zero after stopping.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict

from websockets.asyncio.client import connect

# (phase label, seconds, messages sent at the start of the phase)
SCRIPT = [
    ("baseline", 1.5, []),
    ("sugar", 3.0, [{"type": "sugar", "duration_ms": 3000}]),
    ("sugar+bitter", 3.0, [{"type": "sugar", "duration_ms": 3000},
                           {"type": "bitter", "duration_ms": 3000}]),
    ("bitter", 2.0, [{"type": "bitter", "duration_ms": 2000}]),
    ("stopped", 2.0, [{"type": "stop", "stimulus": "all"}]),
]
SHOWN = ("sugar_grn", "bitter_grn", "mn9", "mn9_primary")


def condition(tick: dict) -> str:
    """Label a tick by which inputs the server says were on."""
    on = [s for s in ("sugar", "bitter") if tick["inputs_hz"].get(s, 0) > 0]
    return "+".join(on) if on else "none"


async def run(url: str, every: int) -> int:
    ticks: list[dict] = []
    async with connect(f"{url}/ws/dashboard") as dash, connect(f"{url}/ws/phone") as phone:
        hello = json.loads(await dash.recv())
        b = hello["brain"]
        print(f"Connected: brain '{b['mode']}' ({b['n_neurons']:,} neurons, backend {b['backend']}), "
              f"groups {', '.join(f'{g}={v['count']}' for g, v in b['groups'].items())}")
        await phone.recv()  # phone hello

        # Round trip for a ping: phone -> server -> phone.
        t0 = time.perf_counter()
        await phone.send(json.dumps({"type": "ping", "t": 1}))
        while json.loads(await phone.recv())["type"] != "pong":
            pass
        print(f"Ping round trip: {(time.perf_counter() - t0) * 1000:.1f} ms\n")

        print(f"{'phase':13s} {'sim t [s]':>9s} {'inputs':>13s} "
              + " ".join(f"{g:>11s}" for g in SHOWN) + f" {'all spikes':>10s} {'ids sent':>8s}")
        phase = {"name": "baseline"}

        async def read_dashboard() -> None:
            while True:
                t = json.loads(await dash.recv())
                if t["type"] != "tick":
                    continue
                t["_phase"] = phase["name"]
                ticks.append(t)
                if t["seq"] % every == 0:
                    counts = " ".join(f"{t['group_counts'].get(g, 0):>11d}" for g in SHOWN)
                    print(f"{phase['name']:13s} {t['t_ms'] / 1000:9.2f} {condition(t):>13s} {counts} "
                          f"{t['total_spikes']:>10d} {len(t['spiking_ids']):>8d}")

        async def drain_phone() -> None:
            while True:
                msg = json.loads(await phone.recv())
                if msg["type"] in ("ack", "error"):
                    print(f"    phone <- {msg['type']}: "
                          + json.dumps({k: v for k, v in msg.items() if k != 'type'}))

        reader = asyncio.create_task(read_dashboard())
        drainer = asyncio.create_task(drain_phone())
        for name, seconds, messages in SCRIPT:
            phase["name"] = name
            for m in messages:
                print(f"    phone -> {json.dumps(m)}")
                await phone.send(json.dumps(m))
            await asyncio.sleep(seconds)
        reader.cancel()
        drainer.cancel()
    return summarize(ticks)


def summarize(ticks: list[dict]) -> int:
    """Per-condition table of mean spikes per tick and MN9 rate; returns the exit code."""
    by: dict[str, list[dict]] = defaultdict(list)
    for t in ticks:
        by[condition(t)].append(t)
    print("\nSummary, grouped by the inputs the server reported (mean spikes per tick):")
    print(f"  {'inputs':13s} {'ticks':>5s} " + " ".join(f"{g:>11s}" for g in SHOWN)
          + f" {'MN9 primary Hz':>15s} {'compute ms':>10s} {'lag ms':>7s}")
    mn9_hz: dict[str, float] = {}
    for cond in ("none", "sugar", "sugar+bitter", "bitter"):
        ts = by.get(cond, [])
        if not ts:
            continue
        mean = {g: sum(t["group_counts"].get(g, 0) for t in ts) / len(ts) for g in SHOWN}
        secs = sum(t["window_ms"] for t in ts) / 1000.0
        mn9_hz[cond] = sum(t["group_counts"]["mn9_primary"] for t in ts) / secs
        comp = sum(t["perf"]["compute_ms"] for t in ts) / len(ts)
        lag = max(t["perf"]["lag_ms"] for t in ts)
        print(f"  {cond:13s} {len(ts):5d} " + " ".join(f"{mean[g]:11.2f}" for g in SHOWN)
              + f" {mn9_hz[cond]:15.1f} {comp:10.1f} {lag:7.1f}")

    after = [t for t in ticks if t["_phase"] == "stopped" and condition(t) == "none"][4:]
    checks = {
        "sugar raises MN9 above baseline": mn9_hz.get("sugar", 0) > mn9_hz.get("none", 0) + 10,
        "adding bitter lowers MN9": mn9_hz.get("sugar+bitter", 1e9) < 0.5 * mn9_hz.get("sugar", 0),
        "bitter alone leaves MN9 silent": mn9_hz.get("bitter", 1e9) < 5,
        "activity returns to zero after stop": bool(after) and all(t["total_spikes"] == 0 for t in after),
    }
    print()
    for name, ok in checks.items():
        print(f"  [{'OK' if ok else 'NOT OK'}] {name}")
    return 0 if all(checks.values()) else 1


def spawn_server(port: int, brain: str) -> subprocess.Popen:
    """Start `python -m server` and wait until /health answers."""
    proc = subprocess.Popen([sys.executable, "-m", "server", "--host", "127.0.0.1",
                             "--port", str(port), "--brain", brain])
    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("server exited during startup")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if json.load(r)["ok"]:
                    return proc
        except OSError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("server did not start")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="ws://127.0.0.1:8000")
    ap.add_argument("--spawn", action="store_true", help="start a server for this run")
    ap.add_argument("--port", type=int, default=8765, help="port for --spawn")
    ap.add_argument("--brain", choices=("reduced", "full"), default="reduced")
    ap.add_argument("--every", type=int, default=2, help="print every Nth tick")
    args = ap.parse_args()
    proc = None
    url = args.url
    if args.spawn:
        proc = spawn_server(args.port, args.brain)
        url = f"ws://127.0.0.1:{args.port}"
    try:
        return asyncio.run(run(url, args.every))
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=30)


if __name__ == "__main__":
    sys.exit(main())

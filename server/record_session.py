"""Record a scripted play session as the dashboard sees it, for replay and tests.

Usage:
    python -m server.record_session --spawn        # start a server, record, stop it
    python -m server.record_session --url ws://127.0.0.1:8000

Connects as a dashboard and as a phone, runs RECORD_SCRIPT, and writes one JSON
object per line to web/dashboard/samples/session.jsonl:

    {"t_wall_ms": 12.3, "src": "dashboard", "msg": {...}}   # received by the dashboard
    {"t_wall_ms": 50.1, "src": "phone",     "msg": {...}}   # sent by the script (context only)

The first line is always the dashboard `hello`. Every message is real server output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect

from server.config import RECORD_SCRIPT
from server.dashboard import SAMPLE_PATH
from server.fake_phone import spawn_server


async def record(url: str, out: Path) -> int:
    lines: list[dict] = []
    t0 = time.perf_counter()

    def stamp(src: str, msg: dict) -> None:
        lines.append({"t_wall_ms": round((time.perf_counter() - t0) * 1000, 1),
                      "src": src, "msg": msg})

    async with connect(f"{url}/ws/dashboard", max_size=None) as dash, \
            connect(f"{url}/ws/phone") as phone:
        hello = json.loads(await dash.recv())
        if hello["type"] != "hello":
            raise RuntimeError(f"expected hello, got {hello['type']}")
        stamp("dashboard", hello)
        await phone.recv()

        async def read_dashboard() -> None:
            while True:
                stamp("dashboard", json.loads(await dash.recv()))

        async def drain_phone() -> None:
            while True:
                await phone.recv()

        # Start from a clean brain so t_ms in the sample begins near 0.
        await dash.send(json.dumps({"type": "reset_brain"}))
        reader = asyncio.create_task(read_dashboard())
        drainer = asyncio.create_task(drain_phone())
        for label, seconds, messages in RECORD_SCRIPT:
            print(f"{label:14s} {seconds:4.1f} s  {' '.join(json.dumps(m) for m in messages)}")
            for m in messages:
                stamp("phone", m)
                await phone.send(json.dumps(m))
            await asyncio.sleep(seconds)
        reader.cancel()
        drainer.cancel()

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line, separators=(",", ":")) + "\n")
    ticks = [x["msg"] for x in lines if x["src"] == "dashboard" and x["msg"]["type"] == "tick"]
    print(f"\nwrote {out} ({out.stat().st_size / 1e6:.2f} MB): {len(lines)} lines, "
          f"{len(ticks)} ticks, seq {ticks[0]['seq']}..{ticks[-1]['seq']}")
    return 0 if ticks else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="ws://127.0.0.1:8000")
    ap.add_argument("--spawn", action="store_true", help="start a server for this run")
    ap.add_argument("--port", type=int, default=8766, help="port for --spawn")
    ap.add_argument("--brain", choices=("reduced", "full"), default="reduced")
    ap.add_argument("--out", type=Path, default=SAMPLE_PATH)
    args = ap.parse_args()
    proc = spawn_server(args.port, args.brain) if args.spawn else None
    url = f"ws://127.0.0.1:{args.port}" if args.spawn else args.url
    try:
        return asyncio.run(record(url, args.out))
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=30)


if __name__ == "__main__":
    sys.exit(main())

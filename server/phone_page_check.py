"""Phase 3 check: the real phone-page logic, driven by mock events, against a live server.

    python -m server.phone_page_check --spawn        # start a reduced-brain server, check, stop
    python -m server.phone_page_check --url http://127.0.0.1:8000   # an already running server

It first fetches the pages and endpoints the phone and dashboard use, then runs
`tests/js/phone_e2e.mjs` in Node. That script loads `web/phone/controller.js` (the same
module the phone page runs) and feeds it a mock tap, mock DeviceMotion samples and mock
camera frames over a real WebSocket. Needs Node 22+ (built-in WebSocket).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from server.fake_phone import spawn_server

ROOT = Path(__file__).resolve().parent.parent
E2E_SCRIPT = ROOT / "tests" / "js" / "phone_e2e.mjs"


def fetch(url: str) -> tuple[int, str, bytes]:
    """(status, content type, body) of a GET request."""
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.headers.get("content-type", ""), r.read()


def check_pages(base: str) -> bool:
    """The phone page, its scripts, the dashboard, the QR code and the config are served."""
    ok = True
    for path, want_type, must_contain in [
        ("/phone/", "text/html", b'id="tap"'),
        ("/phone/phone.js", "javascript", b"requestPermission"),
        ("/phone/controller.js", "javascript", b"createController"),
        ("/phone/phone.css", "text/css", b".tap"),
        ("/dashboard/", "text/html", b"/api/qr.svg"),
        ("/api/qr.svg", "image/svg+xml", b"<svg"),
        ("/api/phone-config", "application/json", b"shake_threshold_ms2"),
    ]:
        try:
            status, ctype, body = fetch(base + path)
            good = status == 200 and want_type in ctype and must_contain in body
        except OSError as e:
            status, ctype, body, good = str(e), "", b"", False
        ok &= good
        print(f"  [{'OK' if good else 'FAIL'}] GET {path:<22} {status} {ctype:<32} {len(body):>6} bytes")
    _, _, body = fetch(base + "/api/phone-url")
    info = json.loads(body)
    print(f"  phone URL for the QR code: {info['url']} (source: {info['source']}, https: {info['https']})")
    return ok


def run(base: str) -> int:
    node = shutil.which("node")
    if node is None:
        print("node not found: install Node.js 22+ to run the mock-event check")
        return 2
    print(f"Pages and endpoints at {base}:")
    pages_ok = check_pages(base)
    print("\nMock-event run (web/phone/controller.js in Node, real WebSocket):")
    proc = subprocess.run([node, str(E2E_SCRIPT), base], cwd=ROOT, text=True,
                          capture_output=True, encoding="utf-8")
    lines = proc.stdout.splitlines()
    print("\n".join(line for line in lines if not line.startswith("RESULT ")))
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)
    ok = pages_ok and proc.returncode == 0
    print(f"\nPhase 3 mock-event check: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="server base URL")
    ap.add_argument("--spawn", action="store_true", help="start a server for this run")
    ap.add_argument("--port", type=int, default=8766, help="port for --spawn")
    ap.add_argument("--brain", choices=("reduced", "full"), default="reduced")
    args = ap.parse_args()
    if not args.spawn:
        return run(args.url.rstrip("/"))
    proc = spawn_server(args.port, args.brain)
    try:
        return run(f"http://127.0.0.1:{args.port}")
    finally:
        proc.terminate()
        proc.wait(timeout=30)


if __name__ == "__main__":
    sys.exit(main())

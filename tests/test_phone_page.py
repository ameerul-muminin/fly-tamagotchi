"""Phase 3: phone page, dashboard QR code, and the mock-event end-to-end test.

The JavaScript tests need Node.js 22+ (built-in WebSocket) on PATH.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import uvicorn

from server import web
from server.app import create_app
from server.config import SERVER, PhoneConfig
from tests.test_server import toy_client, toy_runner

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "tests" / "js"


def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.fail("Node.js 22+ is needed for the phone page tests (not found on PATH)")
    return exe


# ------------------------------------------------------------------ pages and endpoints
def test_pages_are_served():
    with toy_client() as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/dashboard/"
        phone = c.get("/phone/")
        assert phone.status_code == 200 and 'id="tap"' in phone.text and 'id="enable"' in phone.text
        assert 'type="module" src="phone.js"' in phone.text
        for path in ("/phone/phone.js", "/phone/controller.js"):
            r = c.get(path)
            assert r.status_code == 200 and "javascript" in r.headers["content-type"]
        assert c.get("/phone/phone.css").status_code == 200
        dash = c.get("/dashboard/")
        assert dash.status_code == 200 and "/api/qr.svg" in dash.text


def test_qr_code_is_an_svg_for_the_phone_url():
    with toy_client(public_url="https://fly.example.org") as c:
        info = c.get("/api/phone-url").json()
        assert info == {"url": "https://fly.example.org/phone/", "source": "config",
                        "https": True, "note": None}
        r = c.get("/api/qr.svg")
        assert r.status_code == 200 and r.headers["content-type"] == "image/svg+xml"
        root = ET.fromstring(r.content)
        assert root.tag.endswith("svg") and len(root) > 0


def test_phone_url_priority(monkeypatch):
    monkeypatch.setattr(web, "lan_ip", lambda: "192.168.1.23")
    monkeypatch.setattr(web, "ngrok_url", lambda api, timeout: None)
    base = dataclasses.replace(SERVER, public_url=None, port=8000)

    lan = web.phone_url(base)
    assert lan["url"] == "http://192.168.1.23:8000/phone/" and lan["source"] == "lan"
    assert lan["https"] is False and "HTTPS" in lan["note"]

    tls = web.phone_url(dataclasses.replace(base, certfile="c.pem", keyfile="k.pem"))
    assert tls["url"] == "https://192.168.1.23:8000/phone/" and tls["note"] is None

    monkeypatch.setattr(web, "ngrok_url", lambda api, timeout: "https://abc.ngrok-free.app")
    tunnel = web.phone_url(base)
    assert tunnel["url"] == "https://abc.ngrok-free.app/phone/" and tunnel["source"] == "ngrok"

    for given in ("https://x.org", "https://x.org/", "https://x.org/phone", "https://x.org/phone/"):
        assert web.phone_url(dataclasses.replace(base, public_url=given))["url"] == "https://x.org/phone/"


def test_ngrok_absent_is_handled():
    port = free_port()  # nothing listens here
    assert web.ngrok_url(f"http://127.0.0.1:{port}/api/tunnels", 0.3) is None


def test_phone_config_matches_server_config_and_js_defaults():
    with toy_client() as c:
        served = c.get("/api/phone-config").json()
    assert served == json.loads(json.dumps(dataclasses.asdict(PhoneConfig())))
    out = subprocess.run(
        [node(), "--input-type=module", "-e",
         "import {DEFAULTS} from './web/phone/controller.js'; console.log(JSON.stringify(DEFAULTS))"],
        cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == served, "controller.js DEFAULTS drifted from PhoneConfig"


# ------------------------------------------------------------------ JavaScript
def test_phone_controller_unit_tests():
    tests = sorted(str(p.relative_to(ROOT)) for p in JS_DIR.glob("*.test.mjs"))
    assert tests
    r = subprocess.run([node(), "--test", *tests], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", env={**os.environ, "NO_COLOR": "1"})
    assert r.returncode == 0, r.stdout + r.stderr


def test_mock_events_end_to_end_on_toy_brain():
    """The real controller.js, mock tap/shake/camera, a real server over a real socket."""
    cfg = dataclasses.replace(SERVER, brain_mode="toy")
    with running_server(create_app(cfg, runner_factory=toy_runner)) as base:
        r = subprocess.run([node(), str(JS_DIR / "phone_e2e.mjs"), base], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    print(r.stdout)
    result = json.loads(r.stdout.splitlines()[-1].removeprefix("RESULT "))
    failed = [c for c in result["checks"] if not c["ok"]]
    assert r.returncode == 0 and result["ok"] and not failed, failed or r.stderr
    names = {c["name"] for c in result["checks"]}
    assert {"tap sent sugar and the server acked it", "walking motion sends no bitter",
            "shake sent bitter once and the server acked it"} <= names
    assert result["vibrations"] == result["onsets"] >= 2


# ------------------------------------------------------------------ helpers
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class running_server:
    """Run an ASGI app with uvicorn on a free local port in a background thread."""

    def __init__(self, app) -> None:
        self.port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                                    log_level="warning", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        deadline = time.time() + 30
        while not self.server.started:
            if time.time() > deadline or not self.thread.is_alive():
                raise RuntimeError("test server did not start")
            time.sleep(0.05)
        return f"http://127.0.0.1:{self.port}"

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)

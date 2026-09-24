"""Web pages (Phase 3): static phone/dashboard pages, phone URL and QR code.

The phone page is `web/phone/`, the dashboard `web/dashboard/`. The dashboard shows a QR
code for the phone URL, chosen in this order:

1. `ServerConfig.public_url` (or env var FLY_PUBLIC_URL)
2. the public HTTPS URL of a running ngrok tunnel (ngrok's local API)
3. this machine's LAN address, `https` if the server has a certificate, else `http`
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import socket
import urllib.request
from pathlib import Path

import segno
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from server.config import ServerConfig

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PHONE_PATH = "/phone/"


def lan_ip() -> str:
    """This machine's address on the local network (127.0.0.1 if there is none).

    Connecting a UDP socket sends no packets; it only makes the OS pick a route.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ngrok_url(api: str, timeout_s: float) -> str | None:
    """Public HTTPS URL of a running ngrok tunnel, or None if ngrok isn't running."""
    try:
        with urllib.request.urlopen(api, timeout=timeout_s) as r:
            tunnels = json.load(r).get("tunnels", [])
    except (OSError, ValueError):
        return None
    for t in tunnels:
        url = t.get("public_url", "")
        if url.startswith("https://"):
            return url
    return None


def phone_url(cfg: ServerConfig) -> dict:
    """The URL a phone should open, where it came from, and whether it is HTTPS."""
    if cfg.public_url:
        url, source = cfg.public_url, "config"
    elif (tunnel := ngrok_url(cfg.ngrok_api, cfg.ngrok_timeout_s)) is not None:
        url, source = tunnel, "ngrok"
    else:
        scheme = "https" if cfg.certfile else "http"
        url, source = f"{scheme}://{lan_ip()}:{cfg.port}", "lan"
    url = url.rstrip("/")
    if not url.endswith(PHONE_PATH.rstrip("/")):
        url += PHONE_PATH
    elif not url.endswith("/"):
        url += "/"
    https = url.startswith("https://")
    note = None if https else ("Not HTTPS: tap works, but iOS Safari blocks shake and camera. "
                               "Run ngrok or start the server with a certificate.")
    return {"url": url, "source": source, "https": https, "note": note}


def qr_svg(text: str) -> bytes:
    """QR code for `text` as an SVG image."""
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=8, border=2, xmldecl=False,
                                     dark="#111", light="#fff")
    return buf.getvalue()


def add_web_routes(app: FastAPI, cfg: ServerConfig) -> None:
    """Mount the pages and the phone-URL, QR and phone-config endpoints."""

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/dashboard/")

    @app.get("/api/phone-url")
    async def api_phone_url() -> dict:
        return await asyncio.to_thread(phone_url, cfg)  # the ngrok probe may block briefly

    @app.get("/api/qr.svg")
    async def api_qr() -> Response:
        info = await asyncio.to_thread(phone_url, cfg)
        return Response(qr_svg(info["url"]), media_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/phone-config")
    async def api_phone_config() -> dict:
        return dataclasses.asdict(cfg.phone)

    app.mount("/phone", StaticFiles(directory=WEB_DIR / "phone", html=True), name="phone")
    app.mount("/dashboard", StaticFiles(directory=WEB_DIR / "dashboard", html=True),
              name="dashboard")

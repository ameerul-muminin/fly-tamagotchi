"""FastAPI server: phone and dashboard WebSockets around a continuously running brain.

Run: python -m server            (or: uvicorn server.app:app --host 0.0.0.0 --port 8000)
Pages: /dashboard/ (server/dashboard.py) and /phone/ with the QR/phone-URL API (server/web.py).
Brain mode: FLY_BRAIN=reduced (default) or FLY_BRAIN=full.
Message format: reports/MESSAGE_FORMAT.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from server.brain_runner import BrainRunner, EventError, load_runner
from server.config import SERVER, ServerConfig
from server.dashboard import add_dashboard_routes
from server.web import add_web_routes

log = logging.getLogger("fly.server")

ROLES = ("phone", "dashboard")


@dataclass(eq=False)
class Client:
    """One WebSocket connection with its own bounded outgoing queue."""

    ws: WebSocket
    role: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    dropped: int = 0

    def offer(self, text: str) -> None:
        """Queue a message; if the queue is full, drop the oldest one first."""
        if self.queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
                self.dropped += 1
        self.queue.put_nowait(text)


class Hub:
    """Connected clients by role. A slow client only loses its own old messages."""

    def __init__(self, queue_size: int) -> None:
        self.queue_size = queue_size
        self.clients: set[Client] = set()

    def add(self, ws: WebSocket, role: str) -> Client:
        client = Client(ws, role, asyncio.Queue(maxsize=self.queue_size))
        self.clients.add(client)
        return client

    def remove(self, client: Client) -> None:
        self.clients.discard(client)

    def broadcast(self, role: str, msg: dict) -> None:
        text = json.dumps(msg)
        for c in self.clients:
            if c.role == role:
                c.offer(text)

    def count(self) -> dict[str, int]:
        return {r: sum(c.role == r for c in self.clients) for r in ROLES}


class LiveBrain:
    """The runner, the hub and the background loop that ties them together."""

    def __init__(self, runner: BrainRunner, cfg: ServerConfig) -> None:
        self.runner = runner
        self.cfg = cfg
        self.hub = Hub(cfg.client_queue_size)
        self.lag_ms = 0.0
        self.chunks = 0
        self._task: asyncio.Task | None = None
        self._pending_reset = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="brain-loop")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def request_reset(self) -> None:
        """Reset the brain between chunks (never while a chunk is running)."""
        self._pending_reset = True

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        period = self.cfg.chunk_ms / 1000.0
        phone_every = max(1, round(self.cfg.broadcast_hz / self.cfg.phone_status_hz))
        next_t = loop.time()
        r = self.runner
        while True:
            if self._pending_reset:
                r.reset_brain()
                self._pending_reset = False
            r.apply_inputs()
            res = await asyncio.to_thread(r.run_chunk)
            r.accumulate(res)
            self.chunks += 1
            if r.window_ready():
                tick = r.make_tick(self.lag_ms)
                self.hub.broadcast("dashboard", tick)
                if tick["seq"] % phone_every == 0:
                    self.hub.broadcast("phone", r.phone_status())
            if not self.cfg.realtime:
                await asyncio.sleep(0)
                continue
            next_t += period
            delay = next_t - loop.time()
            self.lag_ms = max(0.0, -delay * 1000.0)
            if delay > 0:
                await asyncio.sleep(delay)
            elif self.lag_ms > self.cfg.max_lag_ms:
                next_t = loop.time()  # too far behind: drop the backlog, don't burst


def create_app(cfg: ServerConfig = SERVER,
               runner_factory: Callable[[ServerConfig], BrainRunner] = load_runner) -> FastAPI:
    """Build the app. `runner_factory` lets tests run a small synthetic brain."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        t0 = time.perf_counter()
        runner = await asyncio.to_thread(runner_factory, cfg)
        log.info("brain '%s' loaded: %d neurons in %.1f s", runner.mode, runner.sim.n,
                 time.perf_counter() - t0)
        live = LiveBrain(runner, cfg)
        app.state.live = live
        live.start()
        yield
        await live.stop()

    app = FastAPI(title="Fly Tamagotchi", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        live: LiveBrain = app.state.live
        r = live.runner
        return {"ok": True, "mode": r.mode, "backend": r.sim.backend, "n_neurons": int(r.sim.n),
                "t_ms": r.sim.t_ms, "chunks": live.chunks, "last_compute_ms": r.last_compute_ms,
                "lag_ms": live.lag_ms, "clients": live.hub.count()}

    @app.get("/api/brain")
    async def brain_info() -> dict:
        return app.state.live.runner.info()

    def brain_ids():
        r = app.state.live.runner
        return r.ids, {g: v["ids"] for g, v in r.info()["groups"].items()}

    add_dashboard_routes(app, brain_ids)

    async def serve(ws: WebSocket, role: str) -> None:
        live: LiveBrain = app.state.live
        await ws.accept()
        client = live.hub.add(ws, role)
        client.offer(json.dumps({"type": "hello", "role": role, "brain": live.runner.info(),
                                 "game": live.runner.game_state()}))

        async def sender() -> None:
            while True:
                await ws.send_text(await client.queue.get())

        send_task = asyncio.create_task(sender())
        try:
            while True:
                text = await ws.receive_text()
                client.offer(json.dumps(_reply(live, role, text)))
        except WebSocketDisconnect:
            pass
        finally:
            live.hub.remove(client)
            send_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await send_task

    @app.websocket("/ws/phone")
    async def ws_phone(ws: WebSocket) -> None:
        await serve(ws, "phone")

    @app.websocket("/ws/dashboard")
    async def ws_dashboard(ws: WebSocket) -> None:
        await serve(ws, "dashboard")

    add_web_routes(app, cfg)
    return app


def _reply(live: LiveBrain, role: str, text: str) -> dict:
    """Handle one incoming message and return the reply."""
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return {"type": "error", "error": "invalid JSON"}
    try:
        if role == "dashboard":
            kind = msg.get("type") if isinstance(msg, dict) else None
            if kind == "reset_brain":
                live.request_reset()
                return {"type": "ack", "event": "reset_brain"}
            if kind != "ping":
                raise EventError("dashboard accepts only 'ping' and 'reset_brain'")
        return live.runner.handle_event(msg)
    except EventError as e:
        return {"type": "error", "error": str(e), "received": msg}


app = create_app()

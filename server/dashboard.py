"""Dashboard HTTP routes: the static page and the neuron positions for the 3D view.

`/dashboard/` serves `web/dashboard/`. `/api/positions` returns the positions of the
running brain's neurons (see brain/positions.py). The WebSocket messages the page
reads are unchanged (reports/MESSAGE_FORMAT.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from brain.config import DATA_FILES, PROJECT_ROOT, REDUCED_CIRCUIT_PATH

DASHBOARD_DIR = PROJECT_ROOT / "web" / "dashboard"
SAMPLE_PATH = DASHBOARD_DIR / "samples" / "session.jsonl"

# () -> (root IDs of the running brain, {group: [ID strings]})
BrainIds = Callable[[], tuple[np.ndarray, dict[str, list[str]]]]


def add_dashboard_routes(app: FastAPI, brain_ids: BrainIds) -> None:
    """Mount the dashboard page and `GET /api/positions` on `app`."""
    cache: dict[str, dict] = {}

    @app.get("/api/positions")
    async def positions() -> dict:
        if "body" not in cache:
            from brain.positions import positions_payload
            ids, groups = brain_ids()
            cache["body"] = positions_payload(ids, groups)
        return cache["body"]

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/dashboard/")

    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")


def brain_ids_for_mode(mode: str) -> np.ndarray:
    """Root IDs of a brain mode without loading the connectome (for replay)."""
    if mode == "reduced":
        return np.array(json.loads(Path(REDUCED_CIRCUIT_PATH).read_text())["ids"], dtype=np.int64)
    if mode == "full":
        import pandas as pd
        return pd.read_csv(DATA_FILES["completeness"].path).iloc[:, 0].to_numpy(np.int64)
    raise ValueError(f"no stored neuron list for brain mode {mode!r}")


def create_replay_app(sample: Path = SAMPLE_PATH) -> FastAPI:
    """Dashboard + positions only, no brain: for replaying a recorded session.

    The neuron list comes from the brain mode in the sample's `hello` message.
    """
    hello = json.loads(sample.read_text(encoding="utf-8").splitlines()[0])["msg"]
    brain = hello["brain"]
    app = FastAPI(title="Fly Tamagotchi dashboard replay")
    groups = {g: v["ids"] for g, v in brain["groups"].items()}
    add_dashboard_routes(app, lambda: (brain_ids_for_mode(brain["mode"]), groups))
    return app

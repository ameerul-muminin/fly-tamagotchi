"""Dashboard HTTP routes: the static page, neuron positions and the 3D fly model.

`/dashboard/` serves `web/dashboard/` (no-cache, so an updated page never runs with a
stale script or stylesheet). `/api/positions` returns the positions of the running
brain's neurons, `/api/atlas*` every annotated neuron as the backdrop (see
brain/positions.py), `/api/fly_model.glb` the fly built by `python -m server.fly_model`.
The WebSocket messages the page reads are unchanged (reports/MESSAGE_FORMAT.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
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

    def get_atlas():
        if "atlas" not in cache:
            from brain.positions import atlas, atlas_payload
            ids, _ = brain_ids()
            a = atlas(ids)
            cache["atlas"] = a
            cache["atlas_payload"] = atlas_payload(a)
        return cache["atlas"]

    @app.get("/api/atlas")
    async def atlas_header() -> dict:
        get_atlas()
        return cache["atlas_payload"][0]

    @app.get("/api/atlas.bin")
    async def atlas_body() -> Response:
        get_atlas()
        return Response(cache["atlas_payload"][1], media_type="application/octet-stream")

    @app.get("/api/atlas/neuron/{index}")
    async def atlas_neuron(index: int) -> dict:
        from brain.positions import atlas_neuron as info
        a = get_atlas()
        if not 0 <= index < a.root_ids.size:
            raise HTTPException(404, "no such atlas entry")
        return info(a, index)

    def fly_file(path: Path) -> FileResponse:
        if not path.exists():
            raise HTTPException(404, "fly model not built: run python -m server.fly_model")
        return FileResponse(path, media_type="model/gltf-binary")

    @app.get("/api/fly_model.glb")
    async def fly_model() -> FileResponse:
        from server.fly_model import OUT_PATH
        return fly_file(OUT_PATH)

    @app.get("/api/fly_model_low.glb")
    async def fly_model_low() -> FileResponse:
        from server.fly_model import OUT_LOW_PATH
        return fly_file(OUT_LOW_PATH)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/dashboard/")

    app.mount("/dashboard", NoCacheStatic(directory=DASHBOARD_DIR, html=True), name="dashboard")


class NoCacheStatic(StaticFiles):
    """Static files that the browser must revalidate on every load (ETag still saves
    the download when nothing changed)."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


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

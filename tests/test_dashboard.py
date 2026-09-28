"""Phase 4: dashboard routes, neuron positions, the recorded sample, and the JS tests."""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from brain.config import DATA_FILES, POSITIONS, PROJECT_ROOT
from server.config import SERVER
from server.dashboard import SAMPLE_PATH, brain_ids_for_mode, create_replay_app
from tests.test_server import toy_client

ANN = DATA_FILES["annotations"].path


def sample_lines() -> list[dict]:
    return [json.loads(x) for x in SAMPLE_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]


# ------------------------------------------------------------------ positions
def test_positions_are_voxels_scaled_to_um_for_unchanged_ids_only():
    from brain.positions import neuron_positions
    ann = pd.read_csv(ANN, sep="\t", usecols=["root_id", *POSITIONS.columns], nrows=50).dropna()
    known = ann.root_id.to_numpy(np.int64)[:5]
    fake = np.array([1, 2, 3], dtype=np.int64)  # not FlyWire IDs
    p = neuron_positions(np.concatenate([known, fake]))
    assert p.n_requested == 8 and p.n_missing == 3
    assert set(p.ids.tolist()) == set(known.tolist())
    for rid, xyz in zip(p.ids, p.xyz_um):
        vox = ann.loc[ann.root_id == rid, list(POSITIONS.columns)].to_numpy(float)[0]
        np.testing.assert_allclose(xyz, vox * np.array([0.004, 0.004, 0.040]))


def test_reduced_brain_positions_payload_is_consistent():
    from brain.positions import positions_payload
    ids = brain_ids_for_mode("reduced")
    hello = sample_lines()[0]["msg"]
    groups = {g: v["ids"] for g, v in hello["brain"]["groups"].items()}
    p = positions_payload(ids, groups)
    assert p["n_neurons"] == ids.size == hello["brain"]["n_neurons"]
    assert len(p["xyz"]) == 3 * p["n_placed"] == 3 * len(p["ids"])
    assert set(p["ids"]) <= set(map(str, ids.tolist()))
    placed = set(p["ids"])
    for g, gids in groups.items():
        assert p["groups_unplaced"][g] == [i for i in gids if i not in placed]
    # The readout neuron must be visible in the 3D view.
    assert p["groups_unplaced"]["mn9_primary"] == []
    xyz = np.array(p["xyz"]).reshape(-1, 3)
    # FlyWire brain: roughly 1 mm wide, well under 1 mm in y and z.
    assert (xyz >= 0).all() and xyz[:, 0].max() < 1000 and xyz[:, 1:].max() < 600


# --------------------------------------------------------------------- routes
def test_dashboard_page_and_positions_route_on_live_app():
    with toy_client() as c:
        r = c.get("/dashboard/")
        assert r.status_code == 200 and "Fly Tamagotchi" in r.text
        for f in ("main.js", "state.js", "config.js", "brain3d.js", "brain_logic.js", "fly3d.js",
                  "fly_model3d.js", "fly_motion.js", "ease.js", "sound.js", "phone_link.js",
                  "samples/session.jsonl"):
            r = c.get(f"/dashboard/{f}")
            assert r.status_code == 200, f
            # An updated page must never run with a cached old script or stylesheet.
            assert r.headers["cache-control"] == "no-cache", f
        assert c.get("/", follow_redirects=False).headers["location"] == "/dashboard/"
        p = c.get("/api/positions").json()
        assert p["units"] == "um" and p["n_neurons"] == 10
        assert p["n_placed"] == 0  # toy IDs are not FlyWire neurons: nothing is invented
        assert set(p["groups_unplaced"]) == {"sugar_grn", "bitter_grn", "mn9", "mn9_primary"}


def test_replay_app_serves_positions_for_the_recorded_brain():
    with TestClient(create_replay_app()) as c:
        p = c.get("/api/positions").json()
        assert p["n_placed"] > 0.8 * p["n_neurons"]
        assert c.get("/dashboard/?replay=samples/session.jsonl").status_code == 200


# ---------------------------------------------------- sample vs MESSAGE_FORMAT
TICK_KEYS = {"type", "seq", "t_ms", "window_ms", "server_time_ms", "group_counts", "group_rates_hz",
             "total_spikes", "n_spiking", "spiking_ids", "spiking_ids_truncated", "inputs_hz", "game", "perf"}
GAME_KEYS = {"stimuli_remaining_ms", "light", "mn9_rate_hz", "eating", "mood", "mood_rules_active"}


def test_recorded_sample_follows_the_message_format():
    lines = sample_lines()
    assert lines[0]["src"] == "dashboard" and lines[0]["msg"]["type"] == "hello"
    hello = lines[0]["msg"]
    assert hello["role"] == "dashboard" and hello["brain"]["mode"] == "reduced"
    sizes = {g: v["count"] for g, v in hello["brain"]["groups"].items()}
    assert all(len(v["ids"]) == v["count"] for v in hello["brain"]["groups"].values())

    ticks = [x["msg"] for x in lines if x["src"] == "dashboard" and x["msg"]["type"] == "tick"]
    assert len(ticks) > 300
    assert [t["seq"] for t in ticks] == list(range(ticks[0]["seq"], ticks[0]["seq"] + len(ticks)))
    times = [x["t_wall_ms"] for x in lines]
    assert times == sorted(times)
    for t in ticks:
        assert set(t) == TICK_KEYS and set(t["game"]) == GAME_KEYS
        assert all(isinstance(i, str) for i in t["spiking_ids"])
        assert len(t["spiking_ids"]) <= SERVER.max_spike_ids
        assert len(t["spiking_ids"]) == min(t["n_spiking"], SERVER.max_spike_ids)
        sec = t["window_ms"] / 1000
        for g, n in t["group_counts"].items():
            assert t["group_rates_hz"][g] == pytest.approx(n / sizes[g] / sec)
        assert t["game"]["eating"] == (t["game"]["mn9_rate_hz"] >= SERVER.eating_threshold_hz)


def test_sample_covers_every_scripted_condition():
    ticks = [x["msg"] for x in sample_lines() if x["msg"]["type"] == "tick"]
    cond = {("sugar" if t["inputs_hz"]["sugar"] else "") + ("bitter" if t["inputs_hz"]["bitter"] else "")
            for t in ticks}
    assert {"", "sugar", "bitter", "sugarbitter"} <= cond
    assert any(t["game"]["light"] < 0.3 for t in ticks)
    assert any(t["game"]["eating"] for t in ticks)


# ------------------------------------------------------------------- JS tests
def test_dashboard_js_unit_tests_pass():
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is needed for the dashboard JS tests (web/dashboard/tests)")
    r = subprocess.run([node, "--test", "tests/state.test.mjs", "tests/fun.test.mjs", "tests/brain.test.mjs"],
                       cwd=PROJECT_ROOT / "web" / "dashboard",
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "fail 0" in r.stdout


# ------------------------------------------------------------ whole-brain atlas
def test_atlas_puts_the_simulated_neurons_first_in_positions_order():
    with TestClient(create_replay_app()) as c:
        pos = c.get("/api/positions").json()
        head = c.get("/api/atlas").json()
        body = c.get("/api/atlas.bin").content
        assert head["n_sim"] == pos["n_placed"] and head["n"] > 5 * head["n_sim"]
        xyz = np.frombuffer(body, "<i2").reshape(-1, 3).astype(float) * head["scale_um"]
        assert xyz.shape == (head["n"], 3)
        # Same neurons, same order, same place (within the int16 rounding) as /api/positions.
        p = np.asarray(pos["xyz"]).reshape(-1, 3)
        assert np.abs(xyz[: head["n_sim"]] - p).max() <= head["scale_um"]
        # The annotation table's sides: left hemisphere at smaller x in FlyWire space.
        assert head["left_x_um"] < head["right_x_um"]
        first = c.get("/api/atlas/neuron/0").json()
        assert first["simulated"] and first["root_id"] == pos["ids"][0]
        last = c.get(f"/api/atlas/neuron/{head['n'] - 1}").json()
        assert not last["simulated"] and last["root_id"] not in set(pos["ids"])
        assert c.get(f"/api/atlas/neuron/{head['n']}").status_code == 404


def test_atlas_tooltip_facts_come_from_the_annotation_table():
    with TestClient(create_replay_app()) as c:
        info = c.get("/api/atlas/neuron/0").json()
    row = pd.read_csv(ANN, sep="\t", usecols=["root_id", "cell_type", "side", "top_nt"])
    row = row[row.root_id == int(info["root_id"])].iloc[0]
    assert info["side"] == row.side and info["top_nt"] == row.top_nt
    assert info["cell_type"] == (None if pd.isna(row.cell_type) else row.cell_type)


# ------------------------------------------------------------------- fly model
def test_fly_model_routes_serve_the_built_files_or_404(tmp_path, monkeypatch):
    import server.fly_model as fm
    monkeypatch.setattr(fm, "OUT_PATH", tmp_path / "fly.glb")
    monkeypatch.setattr(fm, "OUT_LOW_PATH", tmp_path / "fly_low.glb")
    with TestClient(create_replay_app()) as c:
        assert c.get("/api/fly_model.glb").status_code == 404
        (tmp_path / "fly_low.glb").write_bytes(b"glTF-test")
        r = c.get("/api/fly_model_low.glb")
        assert r.status_code == 200 and r.content == b"glTF-test"
        assert r.headers["content-type"] == "model/gltf-binary"


MJCF = """<mujoco>
  <default>
    <mesh scale="0.1 0.1 0.1"/>
    <default class="body">
      <geom type="mesh" material="body"/>
      <default class="wing"><joint axis="0 0 1" springref="1.5"/></default>
    </default>
  </default>
  <asset><mesh name="m" file="m.obj"/></asset>
  <worldbody>
    <body name="thorax" childclass="body" pos="0 0 1">
      <geom name="thorax" mesh="m" pos="1 0 0" quat="0 0 0 1"/>
      <geom name="thorax_collision" type="capsule" size="0.1 0.1"/>
      <body name="wing_left" childclass="wing" pos="0 1 0" quat="0.7071 0 0 0.7071">
        <joint name="wing_yaw_left"/>
        <geom name="wing_left_membrane" material="membrane" mesh="m"/>
      </body>
    </body>
  </worldbody>
</mujoco>"""


def test_mjcf_reader_resolves_classes_and_skips_collision_geoms(tmp_path):
    from server.fly_model import read_mjcf
    x = tmp_path / "fly.xml"
    x.write_text(MJCF)
    bodies, joints, geoms, meshes, scale = read_mjcf(x)
    assert [b.name for b in bodies] == ["thorax", "wing_left"] and bodies[1].parent == "thorax"
    assert scale == 0.1 and meshes == {"m": "m.obj"}
    # Joint axis and rest angle come from the "wing" default class.
    assert len(joints) == 1 and joints[0].axis == [0, 0, 1] and joints[0].rest == 1.5
    assert [(g.name, g.material) for g in geoms] == [("thorax", "body"), ("wing_left_membrane", "membrane")]


def test_obj_reader_welds_the_three_vertices_per_triangle(tmp_path):
    from server.fly_model import read_obj
    o = tmp_path / "q.obj"
    # A quad written as two triangles with their own copies of every corner.
    o.write_text("\n".join(["v 0 0 0", "v 1 0 0", "v 1 1 0", "v 0 0 0", "v 1 1 0", "v 0 1 0",
                            "f 1 2 3", "f 4 5 6"]) + "\n")
    v, f = read_obj(o)
    assert v.shape == (4, 3) and f.shape == (2, 3)
    assert len(np.unique(f)) == 4

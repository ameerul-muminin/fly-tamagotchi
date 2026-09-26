"""Server: WebSocket protocol on a tiny synthetic brain, then the real reduced brain."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest
import scipy.sparse as sp
from fastapi.testclient import TestClient

from server.app import Client, create_app
from server.brain_runner import BrainRunner
from server.config import SERVER

# Toy brain: 3 sugar neurons excite both "MN9s", 2 bitter neurons inhibit them.
TOY_GROUPS = {
    "sugar_grn": np.array([0, 1, 2]),
    "bitter_grn": np.array([3, 4]),
    "mn9": np.array([5, 6]),
    "mn9_primary": np.array([5]),
}


def toy_runner(cfg):
    pre, post, w = [], [], []
    for s in TOY_GROUPS["sugar_grn"]:
        for m in TOY_GROUPS["mn9"]:
            pre.append(s), post.append(m), w.append(20.0)
    for b in TOY_GROUPS["bitter_grn"]:
        for m in TOY_GROUPS["mn9"]:
            pre.append(b), post.append(m), w.append(-60.0)
    weights = sp.csr_matrix((w, (pre, post)), shape=(10, 10))
    ids = np.arange(10**17, 10**17 + 10)  # large like FlyWire IDs
    return BrainRunner(weights, ids, TOY_GROUPS, cfg, "toy")


def toy_client(**overrides) -> TestClient:
    cfg = dataclasses.replace(SERVER, brain_mode="toy", **overrides)
    return TestClient(create_app(cfg, runner_factory=toy_runner))


def next_of(ws, kind: str, limit: int = 200) -> dict:
    """Next message of type `kind` (skipping others)."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind!r} message in {limit} messages")


def ticks_where(ws, cond, n: int, limit: int = 400) -> list[dict]:
    """Skip ticks until `cond(tick)` holds, then return the next `n` ticks that satisfy it."""
    out: list[dict] = []
    for _ in range(limit):
        t = next_of(ws, "tick")
        if cond(t):
            out.append(t)
            if len(out) == n:
                return out
    raise AssertionError("condition never held")


def test_hello_describes_the_brain():
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as dash, \
            c.websocket_connect("/ws/phone") as phone:
        for ws, role in ((dash, "dashboard"), (phone, "phone")):
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["role"] == role
            b = hello["brain"]
            assert b["mode"] == "toy" and b["n_neurons"] == 10
            assert b["groups"]["sugar_grn"]["ids"] == [str(10**17 + i) for i in range(3)]
            assert b["light_is_brain_input"] is False
            assert b["eating"] == {"group": SERVER.eating_group,
                                   "threshold_hz": SERVER.eating_threshold_hz,
                                   "window_ms": SERVER.eating_window_ms}
        assert c.get("/health").json()["clients"] == {"phone": 1, "dashboard": 1}


def test_sugar_event_drives_spikes_and_stop_ends_them():
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as dash, \
            c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        rest = ticks_where(dash, lambda t: True, 3)
        assert all(t["total_spikes"] == 0 for t in rest)

        phone.send_json({"type": "sugar", "duration_ms": 5000})
        ack = next_of(phone, "ack")
        assert ack["event"] == "sugar" and ack["active_until_ms"] == pytest.approx(ack["t_ms"] + 5000)
        on = ticks_where(dash, lambda t: t["inputs_hz"]["sugar"] > 0, 6)
        assert sum(t["group_counts"]["sugar_grn"] for t in on) > 0
        assert sum(t["group_counts"]["mn9"] for t in on) > 0
        assert all(t["inputs_hz"]["bitter"] == 0 for t in on)

        phone.send_json({"type": "stop", "stimulus": "sugar"})
        assert next_of(phone, "ack")["event"] == "stop"
        off = ticks_where(dash, lambda t: t["inputs_hz"]["sugar"] == 0, 4)
        assert sum(t["group_counts"]["sugar_grn"] for t in off[1:]) == 0


def test_bitter_reduces_mn9_through_the_weights():
    # The toy wiring makes bitter inhibit MN9; the server has no bitter rule.
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as dash, \
            c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        phone.send_json({"type": "sugar", "duration_ms": 10000})
        sugar = ticks_where(dash, lambda t: t["inputs_hz"]["sugar"] > 0, 10)
        phone.send_json({"type": "bitter", "duration_ms": 10000})
        both = ticks_where(dash, lambda t: t["inputs_hz"]["bitter"] > 0, 10)
        mn9 = lambda ts: sum(t["group_counts"]["mn9"] for t in ts)  # noqa: E731
        assert mn9(both) < mn9(sugar)


def test_stimulus_lasts_exactly_its_duration():
    # Events take effect at the next chunk boundary and last duration_ms of simulated time.
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as dash, \
            c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        phone.send_json({"type": "sugar", "duration_ms": 300})
        ack = next_of(phone, "ack")
        on = ticks_where(dash, lambda t: t["inputs_hz"]["sugar"] > 0, 1)[0]
        n_on = 1
        while next_of(dash, "tick")["inputs_hz"]["sugar"] > 0:
            n_on += 1
        # Tick t_ms is the end of its window; the first "on" window starts at the ack time.
        assert on["t_ms"] - on["window_ms"] == ack["t_ms"]
        assert n_on * SERVER.chunk_ms == 300


def test_light_is_game_state_only():
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as dash, \
            c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        phone.send_json({"type": "light", "level": 0.2})
        assert next_of(phone, "ack")["level"] == 0.2
        t = ticks_where(dash, lambda t: t["game"]["light"] == 0.2, 1)[0]
        assert set(t["inputs_hz"]) == {"sugar", "bitter"} and t["total_spikes"] == 0


def test_invalid_messages_get_errors_and_connection_survives():
    bad = ["not json", json.dumps([1, 2]), json.dumps({"type": "teleport"}),
           json.dumps({"type": "sugar", "duration_ms": -5}),
           json.dumps({"type": "sugar", "duration_ms": "long"}),
           json.dumps({"type": "light", "level": 3}),
           json.dumps({"type": "stop", "stimulus": "salt"})]
    with toy_client() as c, c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        for text in bad:
            phone.send_text(text)
            assert next_of(phone, "error")["error"]
        phone.send_json({"type": "ping", "t": 42})
        assert next_of(phone, "pong")["t"] == 42


def test_duration_is_capped():
    with toy_client() as c, c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        phone.send_json({"type": "bitter", "duration_ms": 10**9})
        assert next_of(phone, "ack")["duration_ms"] == SERVER.max_stimulus_ms


def test_dashboard_can_only_ping_or_reset():
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as dash:
        dash.receive_json()
        dash.send_json({"type": "sugar"})
        assert "dashboard" in next_of(dash, "error")["error"]
        dash.send_json({"type": "reset_brain"})
        assert next_of(dash, "ack")["event"] == "reset_brain"


def test_tick_rate_cap_and_spike_id_cap():
    with toy_client(broadcast_hz=10.0, max_spike_ids=2) as c, \
            c.websocket_connect("/ws/dashboard") as dash, c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        phone.send_json({"type": "sugar", "duration_ms": 5000})
        ticks = ticks_where(dash, lambda t: t["n_spiking"] > 2, 3)
        for t in ticks:
            assert t["window_ms"] >= 100.0          # 10 Hz cap -> 2 chunks per tick
            assert len(t["spiking_ids"]) == 2 and t["spiking_ids_truncated"]
            assert all(isinstance(i, str) for i in t["spiking_ids"])


def test_phone_receives_status():
    with toy_client() as c, c.websocket_connect("/ws/phone") as phone:
        phone.receive_json()
        s = next_of(phone, "status")
        assert {"eating", "mn9_rate_hz", "mood", "light", "stimuli_remaining_ms"} <= s.keys()
        assert s["mood_rules_active"] is False


def test_slow_client_drops_oldest_messages():
    import asyncio

    async def go():
        client = Client(ws=None, role="dashboard", queue=asyncio.Queue(maxsize=3))
        for i in range(5):
            client.offer(str(i))
        return [client.queue.get_nowait() for _ in range(3)], client.dropped

    assert asyncio.run(go()) == (["2", "3", "4"], 2)


# --------------------------------------------------------------- real brain
def test_real_reduced_brain_sugar_and_bitter(connectome):
    """End to end with the real reduced circuit: sugar raises MN9 counts, bitter lowers them."""
    cfg = dataclasses.replace(SERVER, brain_mode="reduced")
    with TestClient(create_app(cfg)) as c, c.websocket_connect("/ws/dashboard") as dash, \
            c.websocket_connect("/ws/phone") as phone:
        assert phone.receive_json()["brain"]["n_neurons"] == 19_698
        rest = ticks_where(dash, lambda t: True, 10)
        phone.send_json({"type": "sugar", "duration_ms": 6000})
        sugar = ticks_where(dash, lambda t: t["inputs_hz"]["sugar"] > 0, 30)
        phone.send_json({"type": "bitter", "duration_ms": 4000})
        both = ticks_where(dash, lambda t: t["inputs_hz"]["bitter"] > 0, 30)
        mn9 = lambda ts: sum(t["group_counts"]["mn9_primary"] for t in ts)  # noqa: E731
        assert mn9(rest) == 0
        assert mn9(sugar) >= 30              # ~85 Hz x 1.5 s expected
        assert mn9(both) < 0.5 * mn9(sugar)  # ~10 Hz expected
        assert c.get("/health").json()["last_compute_ms"] < SERVER.chunk_ms

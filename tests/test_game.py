"""Phase 5: game rules (server/game.py) without a brain, plus their wiring in the server."""

from __future__ import annotations

import dataclasses

import pytest

from server.config import SERVER, GameRules
from server.game import GameState, is_dark, revive, step, sugar_rate_hz
from tests.test_server import next_of, toy_client

R = GameRules()


def run(s: GameState, seconds: float, dt: float = 0.05, **kw) -> GameState:
    kw = {"eating": False, "bitter_hz": 0.0, "light": 1.0} | kw
    for _ in range(round(seconds / dt)):
        s = step(s, dt, rules=R, **kw)
    return s


def start(**kw) -> GameState:
    return dataclasses.replace(GameState.start(R), **kw)


# ------------------------------------------------------------------ hunger
def test_hunger_rises_with_time_alone():
    s = run(start(hunger=0.2), 60)
    assert s.hunger == pytest.approx(0.2 + 60 * R.hunger_rise_per_s, abs=1e-6)


def test_hunger_falls_only_while_the_brain_says_eating():
    fed = run(start(hunger=0.8), 10, eating=True)
    assert fed.hunger == pytest.approx(0.8 + 10 * (R.hunger_rise_per_s - R.hunger_eat_per_s), abs=1e-6)
    # Sugar on the tongue but MN9 below the line: no food gets in.
    assert run(start(hunger=0.8), 10, eating=False).hunger > 0.8


def test_bitter_never_changes_hunger_or_blocks_eating():
    """The golden rule: bitter reduces eating only through the brain. Here, a fly the brain
    says is eating loses exactly as much hunger with or without bitter-neuron spikes."""
    a = run(start(hunger=0.8), 5, eating=True, bitter_hz=0.0)
    b = run(start(hunger=0.8), 5, eating=True, bitter_hz=150.0)
    assert a.hunger == b.hunger
    assert b.happiness < a.happiness  # bitter only costs happiness


# --------------------------------------------------------------- happiness
def test_happiness_up_while_eating_down_with_bitter_spikes():
    assert run(start(), 5, eating=True).happiness > R.start_happiness
    s = run(start(), 3, bitter_hz=R.bitter_hz)
    assert s.happiness == pytest.approx(R.start_happiness - 3 * R.unhappy_bitter_per_s, abs=1e-6)
    assert run(start(), 3, bitter_hz=R.bitter_hz - 1).happiness == R.start_happiness


def test_starving_and_light_while_tired_cost_happiness():
    assert run(start(hunger=R.starving_at), 10).happiness < R.start_happiness
    tired = start(energy=0.1)
    assert run(tired, 10, light=1.0).happiness < R.start_happiness
    assert run(tired, 10, light=0.0).happiness == R.start_happiness  # resting in the dark is fine


# ------------------------------------------------------------------ energy
def test_dark_restores_energy_light_drains_it():
    assert is_dark(R.dark_below - 0.01, R) and not is_dark(R.dark_below, R)
    assert run(start(energy=0.5), 10, light=0.0).energy == pytest.approx(0.5 + 10 * R.energy_dark_per_s)
    assert run(start(energy=0.5), 10, light=1.0).energy == pytest.approx(0.5 + 10 * R.energy_light_per_s)


def test_mood_stays_in_zero_one():
    s = run(start(hunger=0.0, happiness=0.0, energy=1.0), 30, eating=True, bitter_hz=200, light=0.0)
    assert all(0.0 <= v <= 1.0 for v in s.mood().values())
    s = run(start(hunger=1.0, happiness=1.0, energy=0.0), 30)
    assert all(0.0 <= v <= 1.0 for v in s.mood().values())


# ---------------------------------------------------------------- fainting
def test_faints_after_faint_after_s_at_full_hunger_and_freezes():
    s = run(start(hunger=1.0), R.faint_after_s - 0.5)
    assert not s.fainted and s.starving_s == pytest.approx(R.faint_after_s - 0.5)
    s = run(s, 1.0)
    assert s.fainted
    frozen = run(s, 20, eating=True, light=0.0)
    assert frozen == s  # nothing changes until revived


def test_eating_before_the_limit_resets_the_faint_clock():
    s = run(start(hunger=1.0), R.faint_after_s - 5)
    s = run(s, 1.0, eating=True)
    assert s.hunger < 1.0 and s.starving_s == 0.0
    assert not run(s, 10).fainted


def test_revive_gives_a_fresh_fly():
    s = run(start(hunger=1.0), R.faint_after_s + 1)
    assert s.fainted
    assert revive(R) == GameState.start(R)


# ------------------------------------------------ the one game -> brain link
def test_sugar_rate_scales_with_hunger_and_can_be_switched_off():
    assert sugar_rate_hz(150, 0.0, R) == pytest.approx(150 * R.sugar_min_frac)
    assert sugar_rate_hz(150, 1.0, R) == pytest.approx(150)
    assert sugar_rate_hz(150, 0.25, R) < sugar_rate_hz(150, 0.75, R)
    off = dataclasses.replace(R, hunger_scales_sugar=False)
    assert sugar_rate_hz(150, 0.0, off) == 150


# ------------------------------------------------------------- server wiring
def test_hello_carries_the_rules_and_ticks_the_live_mood():
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as ws:
        hello = ws.receive_json()
        assert hello["brain"]["game_rules"]["dark_below"] == R.dark_below
        t = next_of(ws, "tick")
        g = t["game"]
        assert g["mood_rules_active"] is True and g["fainted"] is False
        assert g["dark"] is (g["light"] < R.dark_below)


def test_sugar_input_rate_follows_hunger_on_the_server():
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        next_of(ws, "tick")
        with c.websocket_connect("/ws/phone") as phone:
            phone.receive_json()
            phone.send_json({"type": "sugar", "duration_ms": 3000})
            for _ in range(60):
                t = next_of(ws, "tick")
                if t["inputs_hz"]["sugar"] > 0:
                    break
        hunger = t["game"]["mood"]["hunger"]
        base = SERVER.input_rate_hz["sugar"]
        # The rate was set at the chunk start from the hunger then; hunger moves slowly.
        assert t["inputs_hz"]["sugar"] == pytest.approx(sugar_rate_hz(base, hunger, R), rel=0.02)
        assert t["inputs_hz"]["sugar"] < base


def test_revive_and_reset_restore_the_start_mood():
    with toy_client() as c, c.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        next_of(ws, "tick")
        ws.send_json({"type": "revive"})
        assert next_of(ws, "ack")["event"] == "revive"
        ws.send_json({"type": "reset_brain"})
        assert next_of(ws, "ack")["event"] == "reset_brain"
        t = next_of(ws, "tick")
        assert t["game"]["mood"]["hunger"] == pytest.approx(R.start_hunger, abs=0.01)
        ws.send_json({"type": "feed"})
        assert "revive" in next_of(ws, "error")["error"]

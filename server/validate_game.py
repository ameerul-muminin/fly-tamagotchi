"""Phase 5 validation: the game rules on the real reduced brain, 5 seeds.

Usage: python -m server.validate_game

Runs the server's BrainRunner chunk by chunk (not paced to real time) and checks
G1-G7 from reports/PHASE_5_PLAN.md. Thresholds: server/config.py GameChecks (fixed
before the first run). Results: data/phase5_validation.json. Exit code 0 only if every
check passes.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time

import numpy as np

from brain.config import DATA_DIR, LIFParams
from server.brain_runner import BrainRunner
from server.config import GAME_CHECKS, SERVER, GameChecks, ServerConfig
from server.game import GameState

RESULTS_PATH = DATA_DIR / "phase5_validation.json"


def load_brain():
    """Reduced-circuit weights, IDs and groups (built once, shared by every run)."""
    from brain.connectome import load_connectome
    from brain.reduced import build_reduced_circuit
    from brain.simulator import warm_up
    from brain.validate import group_indices

    params = LIFParams()
    warm_up(params)
    conn = build_reduced_circuit(load_connectome()).connectome
    return conn.weight_matrix(params.w_syn), conn.ids, group_indices(conn, skip_missing=True), params


def run(brain, seed: int, seconds: float, stimuli: tuple[str, ...], start: dict,
        scaling: bool = True, light: float = 1.0) -> dict:
    """Keep `stimuli` on for `seconds` of brain time; return per-chunk traces."""
    weights, ids, groups, params = brain
    cfg: ServerConfig = dataclasses.replace(
        SERVER, seed=seed, realtime=False,
        game=dataclasses.replace(SERVER.game, hunger_scales_sugar=scaling))
    r = BrainRunner(weights, ids, groups, cfg, "reduced", params)
    r.game = dataclasses.replace(GameState.start(cfg.game), **start)
    r.light = light
    tr = {k: [] for k in ("t", "hunger", "happiness", "energy", "eating", "mn9", "sugar_hz")}
    for _ in range(round(seconds * 1000 / cfg.chunk_ms)):
        for s in stimuli:  # keep each stimulus on (events only extend a stimulus)
            r.handle_event({"type": s, "duration_ms": 1000})
        r.apply_inputs()
        r.accumulate(r.run_chunk())
        g = r.game_state()
        tr["t"].append(r.finished_t_ms / 1000)
        tr["hunger"].append(g["mood"]["hunger"])
        tr["happiness"].append(g["mood"]["happiness"])
        tr["energy"].append(g["mood"]["energy"])
        tr["eating"].append(g["eating"])
        tr["mn9"].append(g["mn9_rate_hz"])
        tr["sugar_hz"].append(r.sim.rate("sugar"))
    return {k: np.asarray(v) for k, v in tr.items()}


def mean_sd(xs) -> str:
    xs = np.asarray(xs, float)
    return f"{xs.mean():.3f} ± {xs.std(ddof=1):.3f}"


def validate(c: GameChecks = GAME_CHECKS) -> dict:
    t0 = time.perf_counter()
    brain = load_brain()
    tail = round(c.tail_s * 1000 / SERVER.chunk_ms)
    per_seed = []
    for seed in c.seeds:
        eat = run(brain, seed, c.eat_run_s, ("sugar",), {"hunger": c.hungry_start})
        ctrl = run(brain, seed, c.eat_run_s, ("sugar",), {"hunger": c.hungry_start}, scaling=False)
        bitter = run(brain, seed, c.bitter_s, ("bitter",), {})
        sugar_only = run(brain, seed, c.compare_s, ("sugar",), {"hunger": c.compare_hunger})
        both = run(brain, seed, c.compare_s, ("sugar", "bitter"), {"hunger": c.compare_hunger})
        dark = run(brain, seed, c.dark_s, (), {"energy": c.dark_start_energy}, light=0.0)

        dh = np.diff(np.concatenate([[c.hungry_start], eat["hunger"]]))
        fell = dh < -1e-12
        i20 = np.searchsorted(eat["t"], 20.0)
        per_seed.append({
            "seed": seed,
            # G1: every tick where hunger fell, across all runs with sugar
            "hunger_fell_ticks": int(fell.sum()),
            "hunger_fell_while_eating": int((fell & eat["eating"]).sum()),
            "drop_first_20s": float(c.hungry_start - eat["hunger"][i20 - 1]),
            "tail_eating_frac": float(eat["eating"][-tail:].mean()),
            "final_hunger": float(eat["hunger"][-1]),
            "final_sugar_hz": float(eat["sugar_hz"][-1]),
            "first_stop_hunger": float(eat["hunger"][np.argmax(~eat["eating"][i20:]) + i20])
            if (~eat["eating"][i20:]).any() else None,
            "ctrl_tail_eating_frac": float(ctrl["eating"][-tail:].mean()),
            "ctrl_final_hunger": float(ctrl["hunger"][-1]),
            "happiness_drop_bitter": float(GameState.start(SERVER.game).happiness - bitter["happiness"][-1]),
            "mn9_sugar": float(sugar_only["mn9"].mean()),
            "mn9_sugar_bitter": float(both["mn9"].mean()),
            "energy_gain_dark": float(dark["energy"][-1] - c.dark_start_energy),
        })
    ps = per_seed
    lo, hi = c.satiety_hunger_range
    checks = {
        "G1 hunger falls only while eating": all(s["hunger_fell_ticks"] == s["hunger_fell_while_eating"] for s in ps),
        "G2 a hungry fly eats": all(s["drop_first_20s"] >= c.min_drop_first_20s for s in ps),
        "G3 satiety comes from the brain": all(s["tail_eating_frac"] <= c.max_tail_eating_frac
                                               and lo <= s["final_hunger"] <= hi for s in ps),
        "G4 control: no scaling, no satiety": all(s["ctrl_tail_eating_frac"] >= c.min_tail_eating_frac_no_scaling
                                                  for s in ps),
        "G5 bitter lowers happiness": all(s["happiness_drop_bitter"] >= c.min_happiness_drop for s in ps),
        "G6 sugar + bitter: brain reduces eating": all(s["mn9_sugar_bitter"] < s["mn9_sugar"] for s in ps),
        "G7 dark restores energy": all(s["energy_gain_dark"] >= c.min_energy_gain for s in ps),
    }
    summary = {k: mean_sd([s[k] for s in ps]) for k in (
        "drop_first_20s", "tail_eating_frac", "final_hunger", "final_sugar_hz", "ctrl_tail_eating_frac",
        "ctrl_final_hunger", "happiness_drop_bitter", "mn9_sugar", "mn9_sugar_bitter", "energy_gain_dark")}
    stops = [s["first_stop_hunger"] for s in ps if s["first_stop_hunger"] is not None]
    if len(stops) >= 2:
        summary["first_stop_hunger"] = mean_sd(stops)
    return {"thresholds": dataclasses.asdict(c), "per_seed": ps, "summary": summary, "checks": checks,
            "wall_s": round(time.perf_counter() - t0, 1)}


def main() -> int:
    res = validate()
    RESULTS_PATH.write_text(json.dumps(res, indent=2))
    print("== Phase 5 game rules, reduced brain, seeds", GAME_CHECKS.seeds, "==")
    for k, v in res["summary"].items():
        print(f"  {k:24s} {v}")
    for k, ok in res["checks"].items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {k}")
    print(f"results: {RESULTS_PATH}  ({res['wall_s']} s)")
    ok = all(res["checks"].values())
    print("ALL CHECKS PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

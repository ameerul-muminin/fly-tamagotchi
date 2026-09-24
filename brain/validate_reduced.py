"""Phase 2 validation: reduced circuit vs full brain, shuffled reduced control, speed.

Usage: python -m brain.validate_reduced
Prints the comparison table and speed, writes data/phase2_validation.json.
Same seeds, conditions and input rates as Phase 1 (VALIDATION). With the same
seed, full and reduced runs receive identical Poisson input spikes (same group
sizes and order), so the comparison is paired.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

import numpy as np

from brain.config import (
    PHASE2,
    PHASE2_RESULTS_PATH,
    VALIDATION,
    LIFParams,
    Phase2ValidationConfig,
    ValidationConfig,
)
from brain.connectome import load_connectome, shuffle_connectome
from brain.reduced import build_reduced_circuit, summary
from brain.simulator import LIFSimulator, default_backend
from brain.validate import ConditionResult, group_indices, reduction_is_significant, run_condition

CONDITIONS = ("sugar", "sugar+bitter", "bitter")


def _rates(cfg: ValidationConfig) -> dict[str, dict[str, float]]:
    return {
        "sugar": {"sugar": cfg.sugar_hz},
        "sugar+bitter": {"sugar": cfg.sugar_hz, "bitter": cfg.bitter_hz},
        "bitter": {"bitter": cfg.bitter_hz},
    }


def _warm_up(params: LIFParams) -> None:
    """Load/compile the numba kernel so compile time is not counted as speed."""
    import scipy.sparse as sp
    sim = LIFSimulator(sp.csr_matrix((2, 2)), params)
    sim.set_input("x", np.array([0]), 100.0)
    sim.run(1.0)


def _chunk_stats(times_s: list[float]) -> dict[str, float]:
    ms = np.array(times_s) * 1000.0
    return {"mean": float(ms.mean()), "median": float(np.median(ms)),
            "p95": float(np.percentile(ms, 95)), "max": float(ms.max()), "n_chunks": int(ms.size)}


def _result_dict(r: ConditionResult) -> dict:
    return {**asdict(r), "mean": r.mean, "sd": r.sd}


def run_phase2(cfg: ValidationConfig = VALIDATION, p2: Phase2ValidationConfig = PHASE2,
               params: LIFParams = LIFParams()) -> dict:
    """Run every Phase 2 experiment and return a JSON-serialisable report."""
    _warm_up(params)
    full = load_connectome()
    rc = build_reduced_circuit(full)
    red = rc.connectome
    groups = {"full": group_indices(full), "reduced": group_indices(red, skip_missing=True)}
    weights = {"full": full.weight_matrix(params.w_syn), "reduced": red.weight_matrix(params.w_syn)}
    rates = _rates(cfg)

    times: dict[str, list[float]] = {"full": [], "reduced": []}
    res: dict[str, dict[str, ConditionResult]] = {"full": {}, "reduced": {}}
    for brain in ("full", "reduced"):
        for cond in CONDITIONS:
            res[brain][cond] = run_condition(brain, cond, weights[brain], params, groups[brain],
                                             rates[cond], cfg, times[brain])

    shuffled: dict[int, dict[str, ConditionResult]] = {}
    for s in p2.shuffle_seeds:
        w = shuffle_connectome(red, s).weight_matrix(params.w_syn)
        shuffled[s] = {cond: run_condition(f"reduced-shuffled-{s}", cond, w, params,
                                           groups["reduced"], rates[cond], cfg)
                       for cond in CONDITIONS}

    comparison = {}
    for cond in CONDITIONS:
        f, r = res["full"][cond], res["reduced"][cond]
        comparison[cond] = {
            "full_mean": f.mean, "full_sd": f.sd, "reduced_mean": r.mean, "reduced_sd": r.sd,
            "rel_diff": (r.mean - f.mean) / f.mean if f.mean > 0 else None,
            "seeds_identical": int(sum(a == b for a, b in zip(f.mn9_rates_hz, r.mn9_rates_hz))),
        }

    speed = {"reduced": _chunk_stats(times["reduced"]), "full": _chunk_stats(times["full"])}
    checks = {
        **{f"reduced_matches_full_{c}": comparison[c]["rel_diff"] is not None
           and abs(comparison[c]["rel_diff"]) <= p2.max_rel_diff for c in p2.compared_conditions},
        "reduced_sugar_drives_mn9": res["reduced"]["sugar"].mean >= cfg.min_sugar_mn9_hz,
        "reduced_bitter_reduces_mn9": reduction_is_significant(
            res["reduced"]["sugar"], res["reduced"]["sugar+bitter"], cfg),
        "shuffled_reduced_no_sugar_effect_all_shuffles": all(
            sh["sugar"].mean <= cfg.max_shuffled_mn9_hz for sh in shuffled.values()),
        "shuffled_reduced_no_bitter_effect_all_shuffles": all(
            not reduction_is_significant(sh["sugar"], sh["sugar+bitter"], cfg)
            for sh in shuffled.values()),
        "speed_mean_under_limit": speed["reduced"]["mean"] < p2.max_mean_chunk_ms,
        "speed_p95_under_limit": speed["reduced"]["p95"] < p2.max_p95_chunk_ms,
    }
    checks = {k: bool(v) for k, v in checks.items()}
    return {
        "config": asdict(cfg),
        "phase2_config": asdict(p2),
        "params": asdict(params),
        "backend": default_backend(),
        "circuit": summary(rc, full),
        "full": {c: _result_dict(r) for c, r in res["full"].items()},
        "reduced": {c: _result_dict(r) for c, r in res["reduced"].items()},
        "shuffled_reduced": {str(s): {c: _result_dict(r) for c, r in sh.items()}
                             for s, sh in shuffled.items()},
        "comparison": comparison,
        "speed_ms_per_50ms_chunk": speed,
        "checks": checks,
        "passed": all(checks.values()),
    }


def format_report(rep: dict) -> str:
    """Comparison table, speed and checks as text."""
    c = rep["circuit"]
    seeds = rep["config"]["seeds"]
    lines = [
        f"Reduced circuit: {c['n_neurons']:,} neurons, {c['n_edges']:,} connections "
        f"({c['fraction_of_full_neurons']:.1%} / {c['fraction_of_full_edges']:.1%} of full brain)",
        f"  {c['definition']}",
        "",
        f"MN9 (primary) firing rate [Hz], mean +/- SD over seeds {seeds}, 1 s trials, "
        f"{rep['config']['sugar_hz']:g} Hz inputs:",
        f"  {'condition':14s} {'full brain':>16s} {'reduced':>16s} {'diff':>8s} {'same/seed':>9s}"
        f"   {'shuffled reduced (5 shuffles)':>30s}",
    ]
    for cond, cmp_ in rep["comparison"].items():
        sh = [rep["shuffled_reduced"][s][cond]["mean"] for s in rep["shuffled_reduced"]]
        diff = "n/a" if cmp_["rel_diff"] is None else f"{cmp_['rel_diff']:+.1%}"
        lines.append(
            f"  {cond:14s} {cmp_['full_mean']:7.1f} +/- {cmp_['full_sd']:4.1f}"
            f" {cmp_['reduced_mean']:7.1f} +/- {cmp_['reduced_sd']:4.1f} {diff:>8s}"
            f" {cmp_['seeds_identical']:>5d}/{len(seeds)}"
            f"   mean {np.mean(sh):5.1f}, max {np.max(sh):5.1f}")
    lines.append("  per seed (full | reduced):")
    for cond in rep["comparison"]:
        lines.append(f"    {cond:14s} {rep['full'][cond]['mn9_rates_hz']} | "
                     f"{rep['reduced'][cond]['mn9_rates_hz']}")
    lines.append("  shuffled reduced, per shuffle seed (sugar | sugar+bitter):")
    for s, sh in rep["shuffled_reduced"].items():
        lines.append(f"    {s}: {sh['sugar']['mean']:.1f} | {sh['sugar+bitter']['mean']:.1f}")
    lines.append("")
    lines.append(f"Speed, wall ms per 50 ms simulated (backend: {rep['backend']}):")
    for brain, s in rep["speed_ms_per_50ms_chunk"].items():
        lines.append(f"  {brain:8s} mean {s['mean']:6.1f}  median {s['median']:6.1f}  "
                     f"p95 {s['p95']:6.1f}  max {s['max']:6.1f}  (n={s['n_chunks']})")
    p2 = rep["phase2_config"]
    lines.append(f"  limit: mean and p95 < {p2['max_mean_chunk_ms']:g} ms (reduced)")
    lines.append("")
    for name, ok in rep["checks"].items():
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return "\n".join(lines)


def main() -> int:
    rep = run_phase2()
    print(format_report(rep))
    PHASE2_RESULTS_PATH.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(f"Wrote {PHASE2_RESULTS_PATH}")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

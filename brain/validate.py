"""Phase 1 validation: sugar -> MN9, bitter suppression, shuffled control, speed.

Usage: python -m brain.validate
Writes data/validation_results.json and prints a summary table.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
import scipy.sparse as sp

from brain.config import (
    CHUNK_MS,
    DATA_FILES,
    VALIDATION,
    VALIDATION_RESULTS_PATH,
    LIFParams,
    ValidationConfig,
)
from brain.connectome import Connectome, load_connectome, shuffle_connectome
from brain.neuron_groups import load_groups
from brain.simulator import LIFSimulator


@dataclass
class ConditionResult:
    """MN9 readout rates for one stimulus condition across seeds."""

    brain: str
    condition: str
    input_rates_hz: dict[str, float]
    mn9_rates_hz: list[float]

    @property
    def mean(self) -> float:
        return float(np.mean(self.mn9_rates_hz))

    @property
    def sd(self) -> float:
        return float(np.std(self.mn9_rates_hz, ddof=1)) if len(self.mn9_rates_hz) > 1 else 0.0


def group_indices(conn: Connectome) -> dict[str, np.ndarray]:
    """Neuron groups from data/neuron_groups.json as matrix indices."""
    index = conn.index_of()
    return {name: np.array([index[i] for i in ids], dtype=np.int64)
            for name, ids in load_groups().items()}


def run_trial(
    weights: sp.csr_matrix,
    params: LIFParams,
    inputs: dict[str, tuple[np.ndarray, float]],
    seed: int,
    trial_ms: float,
    chunk_ms: float = CHUNK_MS,
) -> tuple[np.ndarray, list[float]]:
    """Run one trial in chunks; return per-neuron rates [Hz] and wall time per chunk [s]."""
    sim = LIFSimulator(weights, params, seed=seed)
    for name, (idx, rate) in inputs.items():
        sim.set_input(name, idx, rate)
    counts = np.zeros(sim.n, dtype=np.int64)
    chunk_times: list[float] = []
    for _ in range(int(round(trial_ms / chunk_ms))):
        t0 = time.perf_counter()
        counts += sim.run(chunk_ms).counts(sim.n)
        chunk_times.append(time.perf_counter() - t0)
    return counts / (trial_ms / 1000.0), chunk_times


def run_condition(
    brain: str,
    condition: str,
    weights: sp.csr_matrix,
    params: LIFParams,
    groups: dict[str, np.ndarray],
    rates: dict[str, float],
    cfg: ValidationConfig,
    chunk_times: list[float] | None = None,
) -> ConditionResult:
    """Run one condition over all seeds and read out the primary MN9."""
    readout = groups[cfg.groups["readout"]]
    inputs = {g: (groups[cfg.groups[g]], hz) for g, hz in rates.items()}
    mn9 = []
    for seed in cfg.seeds:
        r, ct = run_trial(weights, params, inputs, seed, cfg.trial_ms)
        mn9.append(float(r[readout].mean()))
        if chunk_times is not None:
            chunk_times.extend(ct)
    return ConditionResult(brain, condition, rates, mn9)


def reference_mn9_rate(conn: Connectome, groups: dict[str, np.ndarray],
                       cfg: ValidationConfig) -> tuple[float, float]:
    """Mean and SD (across trials) of the primary MN9 in the repo's own result file."""
    ref = pd.read_parquet(DATA_FILES[cfg.reference_file].path)
    mn9_id = int(conn.ids[groups[cfg.groups["readout"]][0]])
    per_trial = (ref[ref.flywire_id == mn9_id].groupby("trial").size()
                 .reindex(range(cfg.reference_trials), fill_value=0))
    return float(per_trial.mean()), float(per_trial.std(ddof=1))


def reduction_is_significant(sugar: ConditionResult, both: ConditionResult,
                             cfg: ValidationConfig) -> bool:
    """True if sugar+bitter lowers MN9 by the required fraction and number of SDs."""
    if sugar.mean <= 0:
        return False
    drop = sugar.mean - both.mean
    pooled_sd = np.sqrt((sugar.sd ** 2 + both.sd ** 2) / 2)
    return (drop / sugar.mean >= cfg.min_bitter_reduction
            and drop > cfg.min_reduction_sds * pooled_sd)


def evaluate(results: dict[str, ConditionResult], ref_ours: ConditionResult,
             ref_mean: float, cfg: ValidationConfig) -> dict[str, bool]:
    """Apply the Phase 1 pass/fail criteria."""
    real_s, real_sb = results["real/sugar"], results["real/sugar+bitter"]
    shuf_s, shuf_sb = results["shuffled/sugar"], results["shuffled/sugar+bitter"]
    checks = {
        "sugar_drives_mn9": real_s.mean >= cfg.min_sugar_mn9_hz,
        "bitter_reduces_mn9": reduction_is_significant(real_s, real_sb, cfg),
        "shuffled_no_sugar_effect": shuf_s.mean <= cfg.max_shuffled_mn9_hz,
        "shuffled_no_bitter_effect": not reduction_is_significant(shuf_s, shuf_sb, cfg),
        "matches_reference": abs(ref_ours.mean - ref_mean) <= cfg.reference_tolerance * ref_mean,
    }
    return {k: bool(v) for k, v in checks.items()}


def run_validation(cfg: ValidationConfig = VALIDATION, params: LIFParams = LIFParams()) -> dict:
    """Run every Phase 1 experiment and return a JSON-serialisable report."""
    conn = load_connectome()
    groups = group_indices(conn)
    brains = {
        "real": conn.weight_matrix(params.w_syn),
        "shuffled": shuffle_connectome(conn, cfg.shuffle_seed).weight_matrix(params.w_syn),
    }
    conditions = {
        "sugar": {"sugar": cfg.sugar_hz},
        "sugar+bitter": {"sugar": cfg.sugar_hz, "bitter": cfg.bitter_hz},
        "bitter": {"bitter": cfg.bitter_hz},
    }
    chunk_times: list[float] = []
    results: dict[str, ConditionResult] = {}
    for brain, w in brains.items():
        for cond, rates in conditions.items():
            timer = chunk_times if brain == "real" else None
            results[f"{brain}/{cond}"] = run_condition(brain, cond, w, params, groups,
                                                       rates, cfg, timer)

    ref_ours = run_condition("real", f"sugar@{cfg.reference_sugar_hz:g}Hz", brains["real"],
                             params, groups, {"sugar": cfg.reference_sugar_hz}, cfg)
    ref_mean, ref_sd = reference_mn9_rate(conn, groups, cfg)
    checks = evaluate(results, ref_ours, ref_mean, cfg)

    ct = np.array(chunk_times) * 1000.0
    return {
        "config": asdict(cfg),
        "params": asdict(params),
        "n_neurons": conn.n_neurons,
        "n_edges": conn.n_edges,
        "conditions": {k: {**asdict(r), "mean": r.mean, "sd": r.sd} for k, r in results.items()},
        "reference": {
            "file": DATA_FILES[cfg.reference_file].repo_path,
            "sugar_hz": cfg.reference_sugar_hz,
            "theirs_mean": ref_mean, "theirs_sd": ref_sd,
            "ours": {**asdict(ref_ours), "mean": ref_ours.mean, "sd": ref_ours.sd},
        },
        "speed_ms_per_50ms_chunk": {
            "mean": float(ct.mean()), "median": float(np.median(ct)),
            "max": float(ct.max()), "n_chunks": int(ct.size),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def format_report(rep: dict) -> str:
    """Human-readable summary of a validation report."""
    lines = [f"MN9 (primary) firing rate, mean +/- SD over seeds {rep['config']['seeds']}:"]
    for key, r in rep["conditions"].items():
        lines.append(f"  {key:24s} {r['mean']:7.1f} +/- {r['sd']:5.1f} Hz   inputs {r['input_rates_hz']}")
    ref = rep["reference"]
    lines.append(f"Reference (sugar {ref['sugar_hz']:g} Hz): ours {ref['ours']['mean']:.1f} +/- "
                 f"{ref['ours']['sd']:.1f} Hz vs repo {ref['theirs_mean']:.1f} +/- {ref['theirs_sd']:.1f} Hz")
    s = rep["speed_ms_per_50ms_chunk"]
    lines.append(f"Speed: {s['mean']:.1f} ms wall per 50 ms simulated (median {s['median']:.1f}, "
                 f"max {s['max']:.1f}, n={s['n_chunks']}); real-time needs < 50 ms")
    for name, ok in rep["checks"].items():
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return "\n".join(lines)


def main() -> int:
    rep = run_validation()
    print(format_report(rep))
    VALIDATION_RESULTS_PATH.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(f"Wrote {VALIDATION_RESULTS_PATH}")
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Regenerate brian2_tiny_network.npz with the reference implementation.

Runs the Shiu et al. `model.run_trial` (Brian2) on a small random network whose
10 input neurons get Poisson input at 10 kHz, i.e. probability 1 per 0.1 ms step,
so the run is deterministic and can be compared spike-for-spike.

Requires brian2, joblib, pandas, pyarrow and a checkout of
github.com/philshiu/Drosophila_brain_model (commit 91bdd1e). Not needed for tests.

Usage: python tests/fixtures/make_brian2_fixture.py <path to Drosophila_brain_model>
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

N_NEURONS, N_DRAWS, N_INPUTS, T_MS = 300, 6000, 10, 200


def main(repo: str) -> None:
    sys.path.insert(0, repo)
    from brian2 import Hz, ms, prefs
    prefs.codegen.target = "numpy"
    import model

    rng = np.random.default_rng(0)
    pairs = np.unique(rng.integers(0, N_NEURONS, size=(N_DRAWS, 2)), axis=0)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    signed = rng.integers(1, 30, size=len(pairs)) * rng.choice([1, 1, 1, -1], size=len(pairs))
    ids = np.arange(N_NEURONS) + 10**17

    with tempfile.TemporaryDirectory() as tmp:
        comp, con = Path(tmp) / "comp.csv", Path(tmp) / "con.parquet"
        pd.DataFrame({"Completed": True}, index=pd.Index(ids)).to_csv(comp)
        pd.DataFrame({
            "Presynaptic_ID": ids[pairs[:, 0]], "Postsynaptic_ID": ids[pairs[:, 1]],
            "Presynaptic_Index": pairs[:, 0], "Postsynaptic_Index": pairs[:, 1],
            "Connectivity": np.abs(signed), "Excitatory": np.sign(signed),
            "Excitatory x Connectivity": signed,
        }).to_parquet(con)
        params = dict(model.default_params)
        params["r_poi"] = 10000 * Hz
        params["t_run"] = T_MS * ms
        spk = model.run_trial(list(range(N_INPUTS)), [], [], comp, con, params)

    dt = 1e-4  # s
    spikes = np.array(sorted((int(round(float(t) / dt)), int(i))
                             for i, ts in spk.items() for t in ts), dtype=np.int64)
    out = Path(__file__).with_name("brian2_tiny_network.npz")
    np.savez_compressed(out, pre=pairs[:, 0], post=pairs[:, 1], signed_syn=signed,
                        n_inputs=N_INPUTS, t_ms=T_MS, spike_steps=spikes[:, 0],
                        spike_neurons=spikes[:, 1])
    print(f"{len(spikes)} spikes -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])

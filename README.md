# Fly Tamagotchi

A virtual fruit fly whose feeding comes from a simulated connectome. See `PLAN.md`
for the project and `CLAUDE.md` for working rules.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m brain.download_data     # ~130 MB into data/, checksums verified
python -m brain.neuron_groups     # writes data/neuron_groups.json
pytest -q                          # a few minutes; includes full-brain and reduced-circuit validation
python -m brain.validate           # Phase 1 report (full brain), writes data/validation_results.json
python -m brain.validate_reduced   # Phase 2 table: reduced vs full brain, shuffles, speed
```

## Run the server (Phase 2)

```bash
python -m server                   # reduced brain (real time) on port 8000
python -m server --brain full      # full brain (about 65 ms per 50 ms chunk, not real time)
python -m server.fake_phone --spawn   # starts a server, sends fake phone events, prints spike counts
```

WebSockets: `/ws/phone` and `/ws/dashboard`. Every message is documented in
`reports/MESSAGE_FORMAT.md`, and every server setting is in `server/config.py`.

## Data

| What | Source | Version |
|---|---|---|
| Neurons + connectivity | `philshiu/Drosophila_brain_model` @ `91bdd1e`: `2023_03_23_completeness_630_final.csv`, `2023_03_23_connectivity_630_final.parquet` | **FlyWire release 630** (127,400 neurons, 14,687,178 connections): the release the Shiu et al. paper and code use |
| Sugar GRNs, bitter GRNs, MN9 IDs | Parsed from that repo's `figures.ipynb` (Fig 3A and Fig 2 cells) | v630 root IDs |
| Photoreceptor candidates (R7, R8) | `flyconnectome/flywire_annotations` @ `8587524`, `Supplemental_file1_neuron_annotations.tsv` | Annotations are v783; only IDs unchanged in v630 are used |
| Reference results for the sanity check | Repo `results/example/sugarR_100Hz.parquet` | v630 |

All files are pinned by commit and sha256 in `brain/config.py`.

## Brain model

A NumPy/SciPy reimplementation of the Shiu et al. 2024 leaky integrate-and-fire model.
All parameters come from the repo's `model.py` and are listed, with citations, in
`brain/config.py`. The time step (0.1 ms) is Brian2's default, because the repo never sets it.

- Weight = synapse count × sign (`Excitatory x Connectivity` column) × 0.275 mV.
- Stimulated neurons get Poisson input that adds 68.75 mV to v and have no refractory period.
- Each step follows Brian2's schedule. Synaptic or Poisson input that arrives while a
  neuron is refractory is discarded, matching Brian2's conditional-write rule for
  `(unless refractory)` variables.
- On a small test network the simulator gives exactly the same spikes as the repo's own
  Brian2 code (`tests/fixtures/`).

## Phase 1 results (5 seeds, 1 s trials, readout MN9 `720575940660219265`)

| Condition | Real brain | Shuffled brain |
|---|---|---|
| Sugar 150 Hz | 85.8 ± 5.8 Hz | 0.0 ± 0.0 Hz |
| Sugar 150 Hz + bitter 150 Hz | 9.6 ± 3.2 Hz | 0.0 ± 0.0 Hz |
| Bitter 150 Hz | 0.0 ± 0.0 Hz | 0.0 ± 0.0 Hz |

- Sanity check, sugar at 100 Hz: our MN9 rate is 68.4 ± 4.6 Hz, the repo's is 67.0 ± 6.7 Hz (30 trials).
- Speed (Phase 1, NumPy): about 112 ms of wall time per 50 ms simulated, about 2.2× slower than real time. Phase 2 fixes this (below).

## Phase 2: reduced circuit (seeds 0–4, 1 s trials, 150 Hz inputs)

The server runs a reduced circuit: every neuron on a path of at most 5 connections from a
sugar or bitter GRN to an MN9. That is 19,698 neurons and 2,415,250 connections.
The full brain is still available with `--brain full`.

| Condition | Full brain | Reduced circuit | Shuffled reduced (5 shuffles) |
|---|---|---|---|
| Sugar | 85.8 ± 5.8 Hz | 84.2 ± 4.9 Hz (−1.9%) | 0.0 Hz |
| Sugar + bitter | 9.6 ± 3.2 Hz | 9.6 ± 3.2 Hz (0.0%) | 0.0 Hz |
| Bitter | 0.0 Hz | 0.0 Hz | 0.0 Hz |

Speed with the numba kernel:

| Brain | Mean per 50 ms chunk | 95th percentile |
|---|---|---|
| Reduced | 8.4 ms | 12.1 ms |
| Full | 66.7 ms | 97.4 ms |

The simulator has two backends that give identical spikes: NumPy, and numba (the default
when installed).

## Known limitations

- Background noise is implemented but **off by default**. Every noise level tested either
  stayed invisible or eventually ignited a self-sustained runaway state, in the reduced
  circuit and in the full brain. See `reports/PHASE_2_REPORT.md`.

- Only about 21% of annotated R7/R8 photoreceptors have v630 IDs, mostly on the right
  side. Matching the rest would need the FlyWire CAVE API.
- The repo's `sugarR.parquet` example was run at 200 Hz, not the 150 Hz default in
  `model.py`. The sugar neurons in it fire at about 197 Hz.

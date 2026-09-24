# Phase 1 Report: Brain Works Offline

**Status: done.** All five validation checks pass across 5 seeds and `pytest -q` passes (25 tests).
The brain runs about 2.2× slower than real time, which must be fixed before Phase 2
(see Open problems).

## What was built

| File | Purpose |
|---|---|
| `brain/config.py` | All tunable values: LIF parameters (citing `model.py` @ `91bdd1e`), data URLs with sha256, 50 ms chunk size, validation thresholds |
| `brain/download_data.py` | Downloads pinned data files into `data/` and verifies checksums |
| `brain/connectome.py` | Loads v630 neurons and connections, builds the signed sparse weight matrix, builds the shuffled control brain |
| `brain/neuron_groups.py` | Resolves neuron groups from source files and writes `data/neuron_groups.json` with IDs, count and source |
| `brain/simulator.py` | `LIFSimulator`: NumPy/SciPy LIF model, state kept between 50 ms chunks |
| `brain/validate.py` | Runs every Phase 1 experiment, prints the report, writes `data/validation_results.json` |
| `tests/` | 25 tests: simulator unit tests, Brian2 spike-for-spike match, connectome, neuron groups, full-brain behavior |
| `tests/fixtures/` | Spikes from the repo's own Brian2 code on a small network, plus the script that regenerates them |
| `README.md`, `requirements.txt`, `.gitignore`, `pytest.ini` | Setup, data versions, pinned dependencies |

### Data

- **FlyWire release 630** (127,400 neurons, 14,687,178 connections), taken from
  `philshiu/Drosophila_brain_model` at commit `91bdd1e`. This is the release the paper and
  the repo's code use.
- **Sugar GRNs (21), bitter GRNs (21), MN9 (2, primary readout `720575940660219265`)** are
  read programmatically from the repo's `figures.ipynb` (Fig 3A and Fig 2 cells).
  No IDs are typed into code.
- **Photoreceptor candidates:** R7 (286) and R8 (283) from the FlyWire annotation table
  (`flyconnectome/flywire_annotations` @ `8587524`), keeping only IDs that also exist in
  v630.

### Model (from the repo's `model.py`)

| Parameter | Value |
|---|---|
| Resting and reset potential | −52 mV |
| Threshold | −45 mV |
| Membrane time constant | 20 ms |
| Synaptic time constant | 5 ms |
| Refractory period | 2.2 ms |
| Synaptic delay | 1.8 ms |
| Weight per synapse | 0.275 mV |
| Poisson input jump | 0.275 × 250 = 68.75 mV, added directly to v |
| Time step | 0.1 ms (Brian2's default; the repo never sets it) |

Weights are synapse count × sign from the repo's `Excitatory x Connectivity` column.
The GABA/glutamate = inhibitory rule is already applied in that file.

## Test results

### `pytest -q`

```
.........................                                                [100%]
25 passed in 117.06s (0:01:57)
```

### Validation (`python -m brain.validate`)

MN9 (primary) firing rate, 5 seeds (0–4), 1 s trials, 150 Hz Poisson input per stimulated neuron.

| Condition | Real brain | Shuffled brain |
|---|---|---|
| Sugar | **85.8 ± 5.8 Hz** (88, 83, 90, 91, 77) | 0.0 ± 0.0 Hz |
| Sugar + bitter | **9.6 ± 3.2 Hz** (11, 10, 7, 6, 14), 89% lower | 0.0 ± 0.0 Hz |
| Bitter only | 0.0 ± 0.0 Hz | 0.0 ± 0.0 Hz |

| Check | Threshold (set in config before the first validation run) | Result |
|---|---|---|
| Sugar drives MN9 | ≥ 20 Hz | PASS (85.8 Hz) |
| Bitter reduces MN9 | ≥ 25% drop and > 2 pooled SD | PASS (89% drop) |
| Shuffled brain doesn't feed on sugar | MN9 ≤ 5 Hz | PASS (0.0 Hz) |
| Shuffled brain shows no bitter suppression | Reduction test above fails | PASS |
| Matches the repo's own result | Within ±25% | PASS (see below) |

- **Shuffled brain is a real control, not a dead network.** Sugar still drives 91
  downstream neurons (mean 9.4 Hz, max 48 Hz), but the activity never reaches MN9.
  In the real brain, 349 downstream neurons fire.
- **Match with the repo's own results:**
  - With sugar at 100 Hz, our MN9 fires at 68.4 ± 4.6 Hz and the repo's at
    67.0 ± 6.7 Hz (their 30 saved trials).
  - At 200 Hz, ours is 93.8 Hz and theirs 93.3 Hz.
  - Across every active neuron, our rates correlate with theirs at r = 0.998 (100 Hz)
    and 0.999 (200 Hz).
- **Spike-for-spike match:** on a 300-neuron test network with deterministic input,
  our simulator produces the same 14,834 spikes as the repo's `model.run_trial` under
  Brian2.

### Speed

**111.4 ms of wall time per 50 ms simulated** (median 115.0, max 146.6, n = 300 chunks),
about 2.2× slower than real time. Measured with NumPy on the CPU, full 127,400-neuron
brain. The real-time goal is under 50 ms.

## Decisions made

1. **FlyWire v630, not v783.**
   - v630 is what the paper and code use, and all sugar, bitter and MN9 IDs exist in it.
   - In v783, one sugar ID, one bitter ID and one MN9 ID are missing.
2. **Input rate 150 Hz for sugar and bitter.** This is the `r_poi` default in `model.py`.
3. **Sanity reference is the repo's 100 Hz result, not `sugarR.parquet`.**
   - `model.py` says the default rate is 150 Hz, but the sugar neurons in
     `sugarR.parquet` fire at about 197 Hz, so that file was run at 200 Hz.
   - The 100 Hz file sets its rate explicitly. I made this switch before the first
     validation run.
   - Earlier in the session I wrongly described `sugarR.parquet` as a 150 Hz result.
4. **Refractory input is discarded, as in Brian2.**
   - Brian2 applies writes to `(unless refractory)` variables only while a neuron is not
     refractory (`brian2/groups/neurongroup.py`, conditional write).
   - My first version kept that input, which made MN9 fire 19–32% too high. I found the
     bug by stepping through Brian2 and ours side by side, then fixed it.
   - The Brian2 spike-for-spike test now guards against it.
5. **Refractory timing follows Brian2 exactly.** After a spike at step n, the neuron is
   frozen for steps n+1 to n+21, because Brian2 ends refractoriness when
   `timestep(t − lastspike) >= timestep(t_rfc)`.
6. **Stimulated neurons have no refractory period**, as in the repo. Any neuron registered
   as a Poisson input keeps this even if its rate is later set to 0, matching the repo's
   handling of zero-rate inputs.
7. **Shuffle method:** each connection keeps its source neuron and weight, and only the
   target is redrawn at random, rejecting self-connections and duplicates. Neuron count,
   connection count, weight distribution and each neuron's number of outgoing
   connections are unchanged.
8. **Neuron IDs are stored as strings in `neuron_groups.json`.** FlyWire IDs exceed 2^53
   and would lose precision in JavaScript (Phases 3–4).
9. **Photoreceptor IDs matched only when unchanged.** A FlyWire root ID always refers to
   the same segment, so a v783 annotation ID that also exists in v630 is the same neuron.
   IDs edited between releases are not matched.

## Open problems

1. **Too slow for real time (111 ms per 50 ms).** Phase 2 step 1 already covers this:
   build a reduced circuit of neurons within a few connection steps of the inputs and
   MN9, then rerun these tests on it. I haven't yet measured how much that saves.
   Other options: a faster integration loop, or skipping neurons that are at rest
   (only about 400 of 127,400 are active).
2. **Light input: coverage is partial, choice not made.**
   - R7/R8 exist, but only 286 of 1,342 R7 and 283 of 1,324 R8 have v630 IDs, and they
     are mostly on the right side (R7: 210 right / 76 left; R8: 204 / 79).
   - Recovering the rest needs the FlyWire CAVE API, which requires an account.
   - The ocellar photoreceptors themselves aren't in the data, only their downstream
     interneurons.
   - Options: use the partial R7/R8 groups, or make light a game-only input.
3. **The shuffled brain gives exactly 0 Hz for MN9.** This is a clean pass, but it is only
   one shuffle (seed 12345). A stricter control would repeat the check over several
   shuffle seeds.
4. **No `reports/PHASE_1_PLAN.md`.** The planning rule was added to CLAUDE.md after
   Phase 1 was built. The plan was agreed in the conversation instead.

# Phase 2 Report: Reduced Circuit and Server

**Status: done.** All Phase 2 checks pass on seeds 0–4.

- The reduced circuit has 19,698 neurons. Its MN9 rates are within 10% of the full brain:
  −1.9% for sugar and 0.0% for sugar+bitter.
- All 5 shuffled versions of it fail both effects.
- It runs at 8.4 ms mean (12.1 ms p95) per 50 ms chunk.
- The FastAPI server runs the brain live.
- A fake-phone script shows the spike counts changing: MN9 fires at 88.7 Hz with sugar,
  8.3 Hz with sugar+bitter, and 0 Hz with bitter alone or after stopping.
- `pytest -q` passes: 63 tests in 162 s.

One deviation from PLAN.md: **background noise is off by default.** In this model, every
noise level tested either did nothing visible or eventually ignited a self-sustained
runaway state. That happens in the full brain too. See "Findings" below.

## What was built

| File | Purpose |
|---|---|
| `brain/simulator.py` | Faster NumPy backend with the same results: chunk-level Poisson draws, direct CSR delivery, refractory mask. Adds optional background noise on its own random stream, and a backend switch |
| `brain/lif_kernel.py` | numba kernel that runs a whole 50 ms chunk in one compiled call and releases the GIL |
| `brain/reduced.py` | Hop distances, sub-connectome, reduced circuit (`python -m brain.reduced`) |
| `brain/validate_reduced.py` | Phase 2 validation: reduced vs full table, 5 shuffles, speed (`python -m brain.validate_reduced`) |
| `brain/config.py` | New: `NoiseParams`, `ReducedCircuitConfig`, `Phase2ValidationConfig` (thresholds set before the first run) |
| `brain/neuron_groups.py` | R7/R8 groups now carry `"partial": true` and a status saying they are unused |
| `server/config.py` | Every server value: brain mode, rates, durations, broadcast caps, noise, eating readout |
| `server/brain_runner.py` | Live brain: phone events set stimulus timers, rates change between chunks, spikes are summarised into ticks |
| `server/app.py` | FastAPI app: `/ws/phone`, `/ws/dashboard`, `/health`, `/api/brain`, the paced background loop, per-client drop-oldest queues |
| `server/__main__.py` | `python -m server [--brain reduced\|full] [--port]` |
| `server/fake_phone.py` | Sends fake phone events and prints the spike counts (`python -m server.fake_phone --spawn`) |
| `reports/PHASE_2_PLAN.md` | Plan and thresholds, written before the validation run |
| `reports/MESSAGE_FORMAT.md` | Every WebSocket message, with real examples |
| `tests/test_simulator.py` | Every test now runs on both backends. Added: backend equivalence, noise-stream isolation, noise rate |
| `tests/test_reduced.py` | Circuit construction and the Phase 2 validation checks |
| `tests/test_server.py` | Protocol on a 10-neuron toy brain, plus an end-to-end test on the real reduced brain |

## 1. Speed: why the simulator had to change first

Profiling showed that neuron count was not the main cost. Even a 971-neuron circuit took
about 16 ms per chunk, because the NumPy code paid about 33 µs of Python/NumPy overhead
per 0.1 ms step (500 steps per chunk). The largest single cost was `np.isin`.

What I changed:

- **Changes that keep results identical:**
  - Draw a whole chunk's Poisson numbers in one call. NumPy's stream is the same however
    the draws are split, which I checked.
  - Read CSR rows directly.
  - Replace `np.isin` with a boolean refractory mask.
- **A numba kernel** that runs the whole chunk in one call, with the same float operations
  in the same order. The integration loop has no branches, so the compiler can vectorize
  it.

How I checked that nothing changed:

- Both backends pass the Brian2 spike-for-spike test.
- A new test checks that the two backends give bit-identical spikes, `v` and `g`. It covers
  noise, overlapping input groups and rate changes in the middle of a run.
- On seeds 0–4 the full brain gives exactly the Phase 1 numbers again (85.8 ± 5.8 and
  9.6 ± 3.2 Hz).

## 2. Reduced circuit

**Definition:** every neuron with `d_out + d_in ≤ 5`, plus the sugar, bitter and MN9
neurons.

- `d_out` is the number of hops from any sugar or bitter GRN.
- `d_in` is the number of hops to either MN9.
- Hops count every connection, with no synapse threshold.

This is the set of neurons on a path of at most 5 connections from a taste input to MN9.
All connections among these neurons are kept with their original weights.

The circuit has 19,698 neurons (15.5% of the brain) and 2,415,250 connections (16.4%).

**How K = 5 was chosen:** on design seed 100 only, which is not a validation seed. Details
are in `PHASE_2_PLAN.md`.

- K = 4 (5,237 neurons) lost most of the bitter suppression: 5 MN9 spikes against 14 in
  the full brain.
- Counting hops only over strong connections (≥ 3 or ≥ 5 synapses) gave smaller circuits
  that drifted in both directions.
- K = 5 matched the full brain exactly.
- Coverage: every neuron that fires in the full brain lies within 3 hops downstream of the
  GRNs, and K = 5 contains 368/370 of them under sugar and all 362 under sugar+bitter.

**Why the comparison is paired:**

- With the same seed, full and reduced runs receive identical Poisson input spikes (same
  input group sizes and order).
- A neuron that never fires in the full brain has no effect when removed.
- So any difference comes only from removing neurons that do fire.

### Comparison table (`python -m brain.validate_reduced`, seeds 0–4, 1 s trials, 150 Hz)

```
Reduced circuit: 19,698 neurons, 2,415,250 connections (15.5% / 16.4% of full brain)

MN9 (primary) firing rate [Hz], mean +/- SD over seeds (0, 1, 2, 3, 4), 1 s trials, 150 Hz inputs:
  condition            full brain          reduced     diff same/seed    shuffled reduced (5 shuffles)
  sugar             85.8 +/-  5.8    84.2 +/-  4.9    -1.9%     3/5   mean   0.0, max   0.0
  sugar+bitter       9.6 +/-  3.2     9.6 +/-  3.2    +0.0%     5/5   mean   0.0, max   0.0
  bitter             0.0 +/-  0.0     0.0 +/-  0.0      n/a     5/5   mean   0.0, max   0.0
  per seed (full | reduced):
    sugar          [88.0, 83.0, 90.0, 91.0, 77.0] | [87.0, 83.0, 90.0, 84.0, 77.0]
    sugar+bitter   [11.0, 10.0, 7.0, 6.0, 14.0] | [11.0, 10.0, 7.0, 6.0, 14.0]
    bitter         [0.0, 0.0, 0.0, 0.0, 0.0] | [0.0, 0.0, 0.0, 0.0, 0.0]
  shuffled reduced, per shuffle seed (sugar | sugar+bitter):
    12345: 0.0 | 0.0
    12346: 0.0 | 0.0
    12347: 0.0 | 0.0
    12348: 0.0 | 0.0
    12349: 0.0 | 0.0

Speed, wall ms per 50 ms simulated (backend: numba):
  reduced  mean    8.4  median    7.7  p95   12.1  max   18.5  (n=300)
  full     mean   66.7  median   62.0  p95   97.4  max  130.1  (n=300)
  limit: mean and p95 < 35 ms (reduced)

  [PASS] reduced_matches_full_sugar
  [PASS] reduced_matches_full_sugar+bitter
  [PASS] reduced_sugar_drives_mn9
  [PASS] reduced_bitter_reduces_mn9
  [PASS] shuffled_reduced_no_sugar_effect_all_shuffles
  [PASS] shuffled_reduced_no_bitter_effect_all_shuffles
  [PASS] speed_mean_under_limit
  [PASS] speed_p95_under_limit
```

| Check (thresholds fixed in config before this run) | Result |
|---|---|
| Reduced within 10% of full, sugar | PASS (−1.9%) |
| Reduced within 10% of full, sugar+bitter | PASS (0.0%, identical on all 5 seeds) |
| Reduced: sugar drives MN9 (≥ 20 Hz), bitter suppression (≥ 25% and > 2 pooled SD) | PASS (84.2 Hz, 89% drop) |
| Shuffled reduced fails both effects, **for each of 5 shuffle seeds** | PASS (MN9 0.0 Hz in every shuffle) |
| Speed: mean and p95 < 35 ms per 50 ms chunk | PASS (8.4 / 12.1 ms) |

Notes:

- **The full brain is still available.** Use `python -m server --brain full` or
  `FLY_BRAIN=full`. With the numba kernel it now takes 66.7 ms per chunk (it was 111 ms),
  which is still slower than real time.
- **The shuffle control is stricter than in Phase 1.** Phase 1 used 1 shuffle; this uses 5
  (which was Phase 1 open problem 3). Each shuffle keeps the reduced set's neurons, the
  number of connections and every weight, and randomizes the targets.

## 3. Server

**Loop:**

- 50 ms chunks, paced to wall-clock time.
- The simulation runs in a worker thread, and the kernel releases the GIL.
- Input rates change only between chunks, in the event-loop thread, so there are no races.
- If the loop falls more than 250 ms behind, it drops the backlog instead of bursting.

**Phone events:**

- `sugar` and `bitter` drive the GRN group with 150 Hz Poisson input for `duration_ms`.
  The default is 2 s and the cap is 10 s. A new event extends a running stimulus.
- Events take effect at the next chunk boundary and last exactly their duration in
  simulated time; a test checks this.
- `light` is game state only. `stop` and `ping` are also supported.

**Broadcasts:**

- Dashboard ticks at ≤ 20 Hz, each with:
  - spike counts and rates per group
  - total spikes
  - up to 500 sampled spiking IDs as strings
  - input rates
  - game state
  - compute time and lag
- Phone status at ≤ 5 Hz.
- Each client has a queue of 8 messages that drops the oldest first, so a slow client can't
  stall the brain.

**Game state:**

- `eating` is a readout only: the `mn9_primary` rate over the last 500 ms is ≥ 20 Hz, the
  Phase 1 sugar threshold.
- Mood values are placeholders marked `mood_rules_active: false` until Phase 5.
- There is no bitter rule anywhere. Bitter lowers MN9 only through the connectome.

### Fake phone (`python -m server.fake_phone --spawn`)

The script starts a real server and connects over WebSockets as a phone and as a
dashboard. It then sends baseline → sugar (3 s) → sugar+bitter (3 s) → bitter (2 s) → stop.
Each tick is labelled by the input rates the server reports in it. Excerpt from the run
(run with `--every 5`, so every 5th tick is printed; `...` marks rows cut from the report):

```
Connected: brain 'reduced' (19,698 neurons, backend numba), groups sugar_grn=21, bitter_grn=21, mn9=2, mn9_primary=1
Ping round trip: 0.7 ms

phase         sim t [s]        inputs   sugar_grn  bitter_grn         mn9 mn9_primary all spikes ids sent
baseline           1.00          none           0           0           0           0          0        0
baseline           1.25          none           0           0           0           0          0        0
baseline           1.50          none           0           0           0           0          0        0
...
    phone -> {"type": "sugar", "duration_ms": 3000}
    phone <- ack: {"event": "sugar", "duration_ms": 3000.0, "active_until_ms": 5300.0, "t_ms": 2300.0}
sugar              2.50         sugar         148           0          10           6        781      306
sugar              2.75         sugar         149           0           6           3        715      273
sugar              3.00         sugar         151           0           9           5        865      307
...
    phone -> {"type": "sugar", "duration_ms": 3000}
    phone -> {"type": "bitter", "duration_ms": 3000}
    phone <- ack: {"event": "sugar", "duration_ms": 3000.0, "active_until_ms": 8300.0, "t_ms": 5300.0}
    phone <- ack: {"event": "bitter", "duration_ms": 3000.0, "active_until_ms": 8300.0, "t_ms": 5300.0}
sugar+bitter       5.50  sugar+bitter         155         170           1           0        595      178
sugar+bitter       5.75  sugar+bitter         133         151           2           1        556      182
sugar+bitter       6.00  sugar+bitter         168         181           1           0        803      244
...
    phone -> {"type": "bitter", "duration_ms": 2000}
    phone <- ack: {"event": "bitter", "duration_ms": 2000.0, "active_until_ms": 10300.0, "t_ms": 8300.0}
bitter             8.50        bitter           0         168           0           0        271       71
bitter             8.75        bitter           0         150           0           0        212       52
bitter             9.00        bitter           0         159           0           0        238       61
...
    phone -> {"type": "stop", "stimulus": "all"}
    phone <- ack: {"event": "stop", "stimulus": "all", "t_ms": 10350.0}
stopped           10.50          none           0           0           0           0          0        0
stopped           10.75          none           0           0           0           0          0        0
stopped           11.00          none           0           0           0           0          0        0
...

Summary, grouped by the inputs the server reported (mean spikes per tick):
  inputs        ticks   sugar_grn  bitter_grn         mn9 mn9_primary  MN9 primary Hz compute ms  lag ms
  none             71        0.00        0.00        0.00        0.00             0.0       17.1    43.0
  sugar            60      154.53        0.00        7.67        4.43            88.7       16.8     0.0
  sugar+bitter     60      154.05      156.95        1.02        0.42             8.3       19.4    37.0
  bitter           40        0.00      154.12        0.03        0.00             0.0       18.9     0.0

  [OK] sugar raises MN9 above baseline
  [OK] adding bitter lowers MN9
  [OK] bitter alone leaves MN9 silent
  [OK] activity returns to zero after stop
```

The brain is deterministic for a given seed (the server uses seed 0), and chunks at rest
draw no random numbers. So a second run, with sugar starting at a different time, gave
exactly the same stimulus-period sums as the first.

### Server tests

`tests/test_server.py` has 12 tests.

- **Toy brain tests.** Most run on a 10-neuron toy brain, where the wiring makes sugar
  excite MN9 and bitter inhibit it. They cover:
  - the `hello` contents
  - sugar driving spikes and `stop` ending them
  - bitter reducing MN9 through the weights
  - exact stimulus duration
  - light being game-only
  - 7 kinds of invalid message, with the connection staying open
  - the duration cap
  - dashboard permissions
  - the tick-rate cap and the spike-ID cap
  - phone status messages
  - the drop-oldest queue
- **End-to-end test** on the real reduced brain: MN9 is 0 at rest, sugar gives ≥ 30
  spikes in 1.5 s, sugar+bitter gives less than half of that, and compute stays under
  50 ms per chunk.

## Findings

### Runaway activity under background noise (the reason noise is off)

PLAN.md asked for "light background noise". I implemented it as independent Poisson kicks
to every neuron, on a random stream separate from the Poisson inputs, and discarded while a
neuron is refractory. Then I tested it (design seeds 100–102, reduced circuit unless noted):

| Noise (rate per neuron, kick) | What happened |
|---|---|
| 0.2–1 Hz, 8 mV (every kick is a spike) | Within 1 s: about 11k spikes per chunk, and MN9 at about 49 Hz **with no sugar** |
| 0.01 Hz, 8 mV | About 10 spikes per chunk, but MN9 still fired at rest (27 Hz mean over 2 seeds) |
| 20 Hz, 3 mV (below threshold) | 13k spikes per chunk within 1 s |
| 10 Hz, 2 mV (below threshold) | Fine for 1 s: rest silent, sugar and bitter effects intact. Over **60 s at rest**, every seed ignited a self-sustained state: 2.9–12.9 million spikes; in seed 101, from about 13 s on, 244k spikes/s, 4,882 neurons active, the busiest near 300 Hz |
| Full brain, 10 Hz, 2 mV | Ignited within about 1 s: 481k spikes/s, 12,418 neurons active, up to 352 Hz |

What this means:

- The Shiu et al. model has a self-sustained high-activity state.
- Sustained random input eventually ignites it, and the full brain does it faster than the
  reduced circuit, so this isn't an artifact of the reduction.
- The reference model never shows it because it has no background input.
- In that state MN9 can fire without sugar, which would make the fly "eat" because of
  noise. That breaks the golden rule.

What I did:

- The default noise is off (`rate_hz = 0` in `server/config.py`), so the model is the same
  as the validated one.
- Noise stays available as a config option.
- The dashboard can send `reset_brain` to recover from runaway, should it ever happen.

Without noise, activity drops to exactly 0 within about 100 ms of stopping, in the tests
and in the fake-phone run. I also ran a stress check with no noise (the numbers
are MN9 rates, and all spike counts returned to 0 within 1 s every time):

| Stimulus | During | After stopping |
|---|---|---|
| 10 s of sugar+bitter | 7.2 Hz | 0 |
| 20 s of sugar | 82.0 Hz | 0 |
| 10 s of bitter | 0 Hz | 0 |
| 30 rapid sugar taps | | 0 |

None of these ignited the runaway state.

### Live compute time is higher than in the benchmark

- The server reported 12–21 ms of compute per chunk during the fake-phone runs, against
  8.4 ms in validation.
- A direct benchmark in one process gave about 11–12 ms, the same in the main thread and
  in the worker thread. So the gap comes from other load on the machine (the server,
  the client and console output), not from threading.
- All measurements are under the 35 ms budget. Timing on this Windows laptop varied by up
  to about 2× between identical runs.

## Decisions made

1. **Reduced circuit = paths of at most 5 hops from the taste inputs to MN9**, counting all
   connections. It was chosen on design seed 100 before validation. I preferred it to a
   plain "within k hops" ball, which reaches 15,412 neurons downstream at k = 2 and 100,680
   at k = 3.
2. **Paired comparison.** Full and reduced runs use the same seeds and therefore the same
   input spikes. The 10% criterion compares means over seeds 0–4.
3. **Stricter shuffle control:** 5 shuffle seeds, and all of them must fail.
4. **Speed criterion:** both the mean and the 95th percentile must be under 35 ms, a
   stricter reading of "under 35 ms per chunk".
5. **numba added as a dependency.** The NumPy backend stays, gives identical results, and
   is used automatically when numba isn't installed.
6. **Light is game-only.** R7/R8 are saved with `"partial": true` and not wired to any
   input. They aren't in the reduced circuit anyway.
7. **Background noise is off by default** (see Findings).
8. **`eating` readout threshold = 20 Hz** on `mn9_primary` over 500 ms, reusing the Phase 1
   threshold. Phase 5 may tune it in config.
9. **Stimulus timing is in simulated time**, starting at the next chunk boundary. Tapping
   again extends a stimulus and never shortens it.
10. **`httpx2` instead of `httpx`** for FastAPI's test client, because Starlette 1.7
    deprecates `httpx` there.

## Open problems

1. **The runaway state.** A real fly brain has spontaneous activity, but this model has no
   stable state with background activity. The fly can't show "idle" neural flicker
   without risking runaway. Options for later:
   - tiny noise restricted to sensory neurons
   - a visual-only flicker on the dashboard, clearly labelled as not brain data
   - accept a silent brain at rest (the current choice)
2. **The reduced circuit leaves out most of the brain.** The 3D view (Phase 4) can only
   show these 19,698 neurons. The full brain is available but not real time
   (66.7 ms per chunk).
3. **Latency isn't measured end to end yet.** An event waits up to one chunk (50 ms), plus
   compute (about 10–20 ms), plus up to one tick. The ping round trip on localhost is
   about 2 ms. Phase 6 measures tap → reaction.
4. **Windows timer resolution** (about 15 ms) makes pacing jitter a little. The average
   rate holds, and lag is reported in every tick.
5. **Mood values are placeholders** until Phase 5.

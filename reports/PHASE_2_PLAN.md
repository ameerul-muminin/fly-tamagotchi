# Phase 2 Plan: Reduced Circuit and Server

Written before the Phase 2 validation run. Thresholds below are copied into
`brain/config.py` (`Phase2ValidationConfig`) before the first run on the validation seeds.

## Decisions from the goal

1. Build a reduced circuit of neurons within a few connection steps of the sugar, bitter
   and MN9 groups. It must reproduce Phase 1:
   - MN9 rates within 10% of the full brain for sugar and for sugar+bitter, over 5 seeds.
   - The shuffled reduced circuit must still fail.
   - Under 35 ms per 50 ms chunk.
   - The full brain stays available as an option.
2. Light is a game-only input for now. The R7/R8 groups stay in `neuron_groups.json`,
   marked partial.

## Step 1: make the simulator faster (done during design, before validation)

Profiling showed that per-step Python/NumPy overhead dominated, not neuron count. A
971-neuron circuit still took about 16 ms per chunk. Changes, none of which alter the
spikes:

- Draw a chunk's Poisson numbers in one call. NumPy's stream doesn't depend on how draws
  are split, so the numbers and their order are unchanged.
- Read CSR rows directly instead of using scipy row slicing.
- Replace `np.isin` with a refractory mask.
- Add a numba backend (`brain/lif_kernel.py`) that runs a whole chunk in one compiled
  call, with the same float operations in the same order.
- Keep the NumPy backend. Both backends pass the Brian2 spike-for-spike test, and a new
  test checks that they give bit-identical spikes and state.
- The full brain on design seed 100 gives the same MN9 counts before and after.

## Step 2: reduced circuit definition

Definitions:

- `d_out(n)`: the fewest connections from any sugar or bitter GRN to neuron n.
- `d_in(n)`: the fewest connections from n to either MN9.
- Every connection counts, with no synapse-count threshold.

**Circuit** = every neuron with `d_out + d_in <= 5`, i.e. every neuron on some path of at
most 5 connections from a taste input to MN9, plus all sugar, bitter and MN9 neurons.
The simulation keeps every connection between included neurons, with the same weights.

How K = 5 was chosen, using **design seed 100 only** (not a validation seed):

| Candidate | Neurons | Active full-brain neurons included (sugar) | MN9 spikes, seed 100 (full brain: sugar 80, sugar+bitter 14) |
|---|---|---|---|
| path ≤ 4 | 5,237 | 357/370 | 80, **5** (misses bitter suppression badly) |
| path ≤ 5 | 19,698 | 368/370 | 80, 14 (identical) |
| path ≤ 5, hops only over ≥ 5-synapse edges | 3,182 | 332/370 | 85, 17 |
| path ≤ 6, hops only over ≥ 3-synapse edges | 21,738 | 358/370 | 73, 7 |

Why a paired comparison is valid:

- Full and reduced runs with the same seed get identical Poisson input spikes. The input
  groups have the same sizes and the same registration order, so they draw the same
  random numbers.
- The only difference between the two runs is therefore the missing neurons.
- A removed neuron that never fires in the full brain changes nothing.

## Step 3: validation (`python -m brain.validate_reduced`)

Seeds 0–4, 1 s trials, 150 Hz inputs, the same conditions as Phase 1.

| Check | Threshold |
|---|---|
| Reduced vs full, sugar | \|mean_reduced − mean_full\| ≤ 10% of mean_full (primary MN9, mean over seeds 0–4) |
| Reduced vs full, sugar+bitter | same, ≤ 10% |
| Reduced circuit passes the Phase 1 checks | sugar → MN9 ≥ 20 Hz; bitter drop ≥ 25% and > 2 pooled SD |
| Shuffled reduced circuit fails | For **each** of 5 shuffle seeds (12345–12349): sugar → MN9 ≤ 5 Hz, and no significant bitter reduction |
| Speed | Mean **and** 95th percentile < 35 ms wall per 50 ms chunk, over every chunk of the reduced real-brain runs |

Also reported, not pass/fail:

- the bitter-only condition
- the full-brain speed with the new kernel
- the max chunk time

The shuffle keeps the Phase 1 method: same neurons (the reduced set), same number of
connections, same weights, random targets.

## Step 4: server (`server/`)

- `server/config.py` holds every server value:
  - brain mode (`reduced` or `full`, env `FLY_BRAIN`)
  - input rates
  - stimulus durations
  - broadcast cap (20 Hz)
  - spike-ID sample cap (500)
  - background noise
  - phone status rate
  - eating readout threshold
- A background loop runs the brain in 50 ms chunks, paced to real time. The simulation
  runs in a worker thread so the event loop stays responsive.
- Phone events set input rates:
  - `sugar` (on for N ms)
  - `bitter` (on for N ms)
  - `light` (a game-only value, not a brain input)
  - `stop`
  - `ping`
- Rates change only between chunks, in the event-loop thread, so there are no races.
- Broadcasts to the dashboard at ≤ 20 Hz:
  - spike counts and rates per group
  - up to 500 sampled spiking neuron IDs (as strings)
  - input rates
  - game state
  - timing
- Each client gets its own bounded queue, and the oldest message is dropped first, so a
  slow client can't stall the brain.
- Game state for now:
  - the light level
  - active stimuli
  - `eating`, a pure readout: MN9 rate ≥ threshold
  - placeholder mood values, marked inactive until Phase 5
- Background noise: a small Poisson kick to every neuron, from its own random stream, so
  the display shows sparse spontaneous activity.
  - This is a display choice, not part of the reference model.
  - Checked on the design seed so that at rest it doesn't drive MN9 and it doesn't remove
    the sugar/bitter effects.
  - Validation runs use no noise.

## Step 5: proof

- `server/fake_phone.py`:
  - starts the server (or connects to one)
  - sends fake phone events: baseline → sugar → sugar+bitter → bitter → off
  - prints the spike counts per tick and per phase
- `reports/MESSAGE_FORMAT.md` documents every WebSocket message.
- `tests/test_server.py` covers protocol tests on a tiny synthetic brain, plus one test
  with the real reduced brain (sugar raises MN9 counts).
- `tests/test_reduced.py` covers the circuit definition and the Phase 2 validation checks.
- `pytest -q`, then `reports/PHASE_2_REPORT.md`, then a git commit.

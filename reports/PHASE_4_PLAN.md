# Phase 4 Plan: Laptop Dashboard

Goal (PLAN.md, Phase 4): a laptop page with a 2D cartoon fly (idle / eating / disgusted /
resting in the dark), mood bars (hunger, happiness, energy), a 3D brain point cloud where
spiking neurons flash by group, and a live activity chart for sugar, bitter and MN9.
Done when it updates smoothly in real time from server data.

The dashboard only **reads** server messages as documented in `reports/MESSAGE_FORMAT.md`.
It adds no behavior: every number it shows comes from a `tick` or `hello`.

## What gets built

1. **Neuron positions** (`brain/positions.py`)
   - Source: `data/flywire_annotations_783.tsv` (already downloaded, pinned commit),
     columns `pos_x, pos_y, pos_z`: "anchor coordinates in 4x4x40nm voxel space
     (typically on the backbone of the neuron)" (annotations repo,
     `supplemental_files/README.md`). Converted to µm: x·0.004, y·0.004, z·0.04.
   - The brain uses FlyWire v630 root IDs; the annotations use v783. As in
     `brain/neuron_groups.py`, only root IDs present unchanged in both are placed.
     Neurons without a position are not drawn and the count is shown on the page.
     No positions are invented.
2. **Server routes** (`server/dashboard.py`, mounted by `create_app`)
   - `GET /api/positions`: positions of the running brain's neurons (IDs as strings).
   - `GET /dashboard/…`: static files from `web/dashboard/`. `/` redirects there.
   - Message format unchanged (Phase 3 is being built in parallel).
3. **Dashboard page** (`web/dashboard/`, plain ES modules, three.js from jsDelivr, pinned)
   - `config.js`: every display threshold/colour/time constant in one place.
   - `state.js`: pure reducer from messages to display state (no DOM), unit-testable in Node.
   - `fly.js` (SVG cartoon), `chart.js` (canvas), `brain3d.js` (three.js points),
     `source.js` (live WebSocket or recorded-sample replay), `main.js` (wiring).
   - Fly state is a display readout with fixed priority:
     eating (`game.eating`, i.e. MN9 spikes) > disgusted (bitter GRN spike rate) >
     resting (`game.light` dark, a game-only input) > idle.
   - Mood bars show `game.mood` and label them "placeholder" while
     `mood_rules_active` is false (Phase 5 adds the rules; no rules are added here).
4. **Recorded sample** (`server/record_session.py` → `web/dashboard/samples/session.jsonl`)
   - Real messages from the reduced brain: baseline → sugar → bitter → sugar+bitter →
     dark → light. Replay: `/dashboard/?replay=samples/session.jsonl`.
5. **Tests**
   - `tests/test_dashboard.py`: positions (units, only unchanged IDs, all groups placed or
     reported), routes, sample conforms to MESSAGE_FORMAT.md, and the Node test runner.
   - `web/dashboard/tests/state.test.mjs`: reducer on the recorded sample — each fly state
     appears in the matching stimulus phase, chart buffers, flash bookkeeping, seq gaps.
6. **Validation** (`python -m server.validate_dashboard`): headless Chrome over CDP.
   - Replay: the page renders the sample (points drawn, all four fly states seen, chart
     has data, no JS errors) and a screenshot is saved to `reports/`.
   - Live: real server + scripted fake phone; measure in the page.

## Thresholds (fixed before the first validation run, in `server/config.py` `DASHBOARD_CHECKS`)

| Check | Threshold |
|---|---|
| Live tick receive rate | ≥ 0.9 × `broadcast_hz` (18 Hz) |
| Ticks lost (seq gaps) | ≤ 2 % |
| Render frame rate (headless Chrome) | ≥ 30 fps median |
| Tick age at render (p95, `Date.now() - server_time_ms`) | ≤ 150 ms |
| JS errors on page | 0 |
| Replay: fly states seen | all 4 |

## Decisions

- three.js from a pinned CDN URL instead of vendoring 1 MB into git. Offline use needs a
  local copy (open problem, noted in the report).
- The recorded sample is committed (it is our own server output, not connectome data), so
  the Node tests run without the brain. Positions are not committed; they come from `data/`.

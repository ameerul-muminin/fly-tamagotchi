# CLAUDE.md: Fly Tamagotchi

Full spec lives in `PLAN.md`. Read it before any work. This file holds the working rules.

## Golden rule
Fly behavior must come from simulated spikes, never from game logic.
The fly eats only if MN9 neurons actually fire. Bitter reduces eating only through the brain.
If you are tempted to add an `if bitter: eat_less` rule, stop and flag it.

## How to work (autonomous mode)
- I usually run you with `/goal`. Do not stop to ask for approval. Make reasonable decisions and log them.
- Work on ONE phase at a time. Do not start the next phase unless the goal says so.
- At the start of a phase, write your plan to `reports/PHASE_N_PLAN.md`, then build.
- At the end of a phase, write `reports/PHASE_N_REPORT.md`: what was built, test results (numbers), decisions made, open problems.
- Prove "done" in the conversation: run `pytest -q` and the phase's validation script, and show the output. Claims without output don't count.
- Never loosen a test threshold, delete a test, or skip a test to make it pass. Test thresholds are set in config BEFORE the first validation run. If a result is genuinely wrong, write it in the report instead.
- If you are truly blocked (missing data, broken download, unclear science), write the blocker at the top of the report and say "BLOCKED" clearly. Don't fake a workaround.
- Commit to git after each working milestone with a clear message.
- If data, an API, or a paper detail is unclear, say so. Do not invent values.

## Neuron IDs
- Never hard-code guessed neuron IDs.
- Resolve groups (sugar GRNs, bitter GRNs, MN9, photoreceptors) from the annotation files or the Shiu et al. repo.
- Save resolved groups to `data/neuron_groups.json` with, for each group: IDs, count, and the source (file + column/filter or repo reference).
- A test must check every group is non-empty and every ID exists in the weight matrix.

## Brain model
- Reference: Shiu et al. 2024, `github.com/philshiu/Drosophila_brain_model`.
- Take LIF parameters (thresholds, time constants, refractory period, weight scaling, Poisson input rate) from that repo's code, not from memory. Put them in one config with a comment citing the source file.
- Use the same FlyWire data release the repo uses. Note the version in the README.
- Weights: synapse count × sign (inhibitory for GABA/glutamate as in the repo; match its convention exactly).
- Simulator runs in 50 ms chunks, keeps state between chunks, uses scipy.sparse (PyTorch optional if a GPU exists).
- Sanity check: on a short run, our firing rates for sugar → MN9 should roughly match the repo's own results.

## Validation (Phase 1)
- Run each test across at least 5 random seeds. Report mean ± SD firing rates.
- Tests: sugar → MN9 fires; sugar + bitter → MN9 reduced; shuffled brain (same neuron count, same number of connections, same weight distribution) does NOT reproduce either effect.
- Report speed: wall-clock time per 50 ms of simulated time. Real-time goal: under 50 ms.

## Environment
- Python 3.11+, virtual env in `.venv/`.
- Core deps: numpy, scipy, pandas, pyarrow, pytest. Later: fastapi, uvicorn, websockets.
- `data/` is gitignored. Downloads go through `brain/download_data.py`, never committed.
- Keep a `requirements.txt` up to date.

## Code style
- Type hints, small modules, docstrings on public functions.
- All tunable values in config, not scattered in code.
- `pytest -q` must pass before reporting a phase done.

## Commands
- Setup: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
  (Windows: `.venv\Scripts\activate`)
- Get data: `python -m brain.download_data`
- Tests: `pytest -q`

## Later phases (reminders)
- Safari needs HTTPS for motion and camera: use mkcert or ngrok.
- iOS needs a user-tap button to request DeviceMotion permission.
- Target latency tap → fly reaction under ~300 ms. If too slow, reduce to neurons within a few hops of inputs/outputs and document it.
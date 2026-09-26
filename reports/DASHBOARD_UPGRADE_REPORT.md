# Dashboard upgrade: 3D fly, new layout, "Hear the brain"

Asked for after Phase 4: make the dashboard more fun and shareable, improve the fly with
three.js. Of the features offered, the user chose "Hear the brain" (spikes as sound).
This is display work only: no change to the brain, the inputs or the eating readout.

## What was built

| Part | Files | What it does |
|---|---|---|
| 3D fly | `web/dashboard/fly3d.js`, `fly_motion.js` | A Drosophila built from three.js primitives (no model download): compound eyes with ommatidia, banded abdomen, veined iridescent wings, bristles, six legs with planted feet, feathery aristae, proboscis. Stands on a dish with a true 1 mm scale bar. Drag to turn. |
| Layout | `index.html`, `style.css` | The fly stage is the hero (a microscope-style view with the state in large type and a gulp counter). New panel "Why it's doing that". Sentence-case headings, Bricolage Grotesque + Atkinson Hyperlegible. Works at phone width. |
| Why it's doing that | `main.js` | Meters for sugar neurons, bitter neurons and MN9, with the server's eating threshold drawn on the MN9 meter, and a plain sentence on the current state. |
| Gulps | `state.js` | Counts `game.eating` false → true onsets this session. |
| Hear the brain | `sound.js` | WebAudio. Each tick's spikes are scheduled across the next 50 ms: MN9 spike = deep thump, sugar neurons = bright pluck, bitter = low buzz, others = soft click; gulp / "blech" cues on state changes. Button in the header (browsers need a click before audio). |
| Eating threshold in `hello` | `server/brain_runner.py` | `brain.eating = {group, threshold_hz, window_ms}` so the page draws the real threshold instead of copying the number. Documented in `MESSAGE_FORMAT.md`. |

## Golden rule check

- The proboscis extends only in the `eating` state, which is `game.eating` (MN9 ≥ 20 Hz over
  500 ms, from spikes). The pump rate is set by the MN9 rate. Test: "only the eating pose
  extends the proboscis", "the pump follows MN9".
- Disgust (buzzing, grooming, puffs) is bitter-neuron spikes ≥ 20 Hz (unchanged Phase 4 rule).
- Every sound comes from spike counts in a tick. Test: "a silent brain plays nothing" and,
  over the whole recorded session, "sound happens only in ticks with spikes".
- Belly swelling while eating and the gulp counter are drawings of MN9-driven eating, not rules.
- The page says in words which parts are game rules (darkness → resting).

## Results

- `pytest -q`: **77 passed** (the dashboard JS suite now runs 24 Node tests: 10 existing + 14 new).
- `python -m server.validate_dashboard`: **ALL CHECKS PASS**. Live: 20.01 Hz ticks, 0% lost,
  median **30.0 fps** under SwiftShader (blank page 59.9), p95 tick age 40.5 ms, no JS errors.
  Added one check: "3D fly drawn (not the 2D fallback)".
- Real GPU (AMD Radeon 860M, headless Edge with D3D11): quality `high`, **59.9 fps** in every
  state, no JS errors. The sound button turns on ("Listening") with no errors. Audio output
  itself was not listened to: there is no speaker in the test setup.

## Decisions

1. **Automatic render quality.** The validator renders with SwiftShader (software GL). There,
   the brain view alone already sits at the 30 fps line; the full-quality fly took the page to
   7.5 fps. Measured: shadows+reflections off → 15, plus lower resolution → 20, plus the dish
   hidden → 29.9. So the fly picks its quality from the WebGL renderer name: software renderers
   (SwiftShader, llvmpipe, Microsoft Basic Render) get `low` (no antialiasing, shadows or
   reflections, 0.6× resolution, unlit dish, fly drawn at most 20 times a second). Any other
   renderer gets `high`, which drops shadows and reflections by itself if the median frame
   takes over 40 ms. `?quality=high|low` forces either. The 30 fps threshold was not changed.
   This means **the validator measures the low-quality fly**; high quality was measured
   separately on the GPU (above).
2. **No postprocessing (bloom).** Not affordable under software GL; the brain view's additive
   blending already glows.
3. **Primitives, not a downloaded model.** No licensing questions and no extra files; the
   anatomy is simplified (e.g. no leg hairs, legs are three straight segments).
4. **The 2D fly stays** as the fallback when three.js can't load (it comes from a CDN).
5. **Re-recorded `samples/session.jsonl`** so replays include `brain.eating`. Same script,
   371 ticks; the tests on the sample pass unchanged.

## Open problems

- The dark threshold still differs between the phone page (0.15) and the dashboard (0.3);
  left for the user to decide (see the merge notes).
- Sound was checked for errors, not by ear.
- The narrow-screen camera widening was tuned from one screenshot (390 px wide).

# Dashboard redesign: flybody fly, whole-brain view, new phone page

Asked for after the dashboard upgrade. The user shared a reference UI (a front-view point
cloud brain with Resting / Stimulated / Firing states and hover tooltips, next to a realistic
3D fly with Side / Top / Follow cameras and a 1 mm scale bar) and asked for that look, using
two skills: `emil-design-eng` (Emil Kowalski) and `better-ui` (Jakub Krehel). Then: "also
make the UI of the mobile better too" (the phone controller page).

This is display work only. The brain, its inputs and the eating readout did not change.

## What was built

| Part | Files | What it does |
|---|---|---|
| Fly model build | `server/fly_model.py` | Downloads the **flybody** fly (Vaxenburg et al. 2025, Nature, doi:10.1038/s41586-025-09029-4; `TuragaLab/flybody` @ `d015e9b`, Apache-2.0): MJCF body tree + 85 OBJ meshes (~140 MB into `data/flybody/`). Welds vertices, simplifies each mesh (quadric decimation), writes two GLBs: `fly.glb` (132k triangles, 1.7 MB) and `fly_low.glb` (36k, no bristles, 0.5 MB). Joints (102: axis, rest angle, range) go in the scene extras. |
| 3D fly | `web/dashboard/fly_model3d.js`, `ease.js` | Loads the GLB for the render quality, poses the model through its own MuJoCo joints: proboscis (rostrum, haustellum, labellum), head, antennae, wings, front legs (grooming), abdomen (breathing). Side / Top / Follow cameras with a 650 ms eased move; a true 1 mm scale bar. Food drops sized so the extended labellum dips into them. Falls back to `fly3d.js` without the model, to the 2D fly without three.js. |
| Brain view | `web/dashboard/brain3d.js`, `brain_logic.js` | Front view. **All 139,248** neurons with a position in the FlyWire annotation table are drawn as the backdrop; the **17,101** simulated ones can be *resting*, *stimulated* (the phone input drives their group now: `hello.brain.stimuli` + `tick.inputs_hz`) or *firing* (a spike in a recent tick). Chips All / Sugar / Bitter / MN9 highlight a group with a ring. Hover shows the FlyWire annotation (cell type · side, transmitter, ID, simulated or not). L / R labels are placed from the table's `side` column and swap if the brain is turned around. |
| Server | `brain/positions.py`, `server/dashboard.py` | `/api/atlas` + `/api/atlas.bin` (int16 positions, simulated neurons first in `/api/positions` order), `/api/atlas/neuron/{i}` (tooltip), `/api/fly_model.glb`, `/api/fly_model_low.glb`. Dashboard and phone static files now send `Cache-Control: no-cache` (fixes the stale `style.css`/`main.js` mix the user saw after the last upgrade). |
| Layout | `web/dashboard/index.html`, `style.css`, `main.js`, `chart.js` | Two viewers side by side (brain, fly) with overlaid labels as in the reference; panels below. Stacks to one column at phone width. |
| Phone page | `web/phone/index.html`, `phone.css` | Same visual language: status card with a state ring, compact mood row, a warm sugar tap zone as the hero, sensor cards with icons, a clear "Enable shake + camera" button. Every ID `phone.js` and the tests use is unchanged. |

## How the two skills were applied

- Surfaces: shadow rings (`0 0 0 1px oklch(1 0 0 / 0.08)`) instead of borders, concentric radii
  (segmented control 10 px outer, 3 px padding, 7 px inner), image outline on the QR code.
- Press feedback: `scale: 0.96` on every button, tab and the tap zone, 150 ms ease-out.
- Exact transition properties everywhere (no `transition: all`); custom curves
  `cubic-bezier(0.23, 1, 0.32, 1)` (ease-out) and `cubic-bezier(0.77, 0, 0.175, 1)` (the fly
  camera's on-screen move, shared with JS through `ease.js`).
- Sound button icon: both icons stay in the DOM and cross-fade with opacity, `scale 0.25 → 1`
  and `blur 4px → 0`, `cubic-bezier(0.2, 0, 0, 1)`, 300 ms.
- Tooltip: 125 ms enter from `scale(0.97)`, origin at the pointer side; moving to the next
  neuron updates it instantly (no re-animation).
- Tab underline and segment thumb slide with `transform`; hover effects only under
  `(hover: hover) and (pointer: fine)`; `prefers-reduced-motion` turns off slides, pulses and
  the camera move.

## Golden rule check

- Eating is still only `game.eating` (MN9 ≥ 20 Hz over 500 ms, from spikes). The proboscis goes
  out only in the eating pose; the pump rate follows MN9 (`fly_motion.js`, unchanged tests).
- *Stimulated* is read from the server's input rates, *firing* from `spiking_ids`. Non-simulated
  neurons are drawn dim and are never lit; the tooltip says "Not in the simulated circuit".
- The droplet shows which input is on; it does not change anything the brain does.

## Results

- `pytest -q`: **82 passed** (was 77). New: atlas order/positions vs `/api/positions`, atlas
  tooltip vs the annotation table, fly-model routes (404 until built), `no-cache` headers,
  MJCF class resolution, OBJ welding, and 8 Node tests (`tests/brain.test.mjs`: stimulated
  groups across the whole recorded session, picking, L/R, labels, easing curve).
- `python -m server.validate_dashboard`: **ALL CHECKS PASS**, twice in a row after the last
  change: live tick rate 20.09 / 20.17 Hz, 0 % lost, median **30.0 fps** under SwiftShader
  (blank page 59.9), p95 tick age 40.9 / 40.3 ms. Two checks added: "flybody model drawn
  (when built)" and "whole-brain backdrop drawn".
- Real GPU (AMD Radeon 860M, headless Edge, D3D11): full model with shadows, **59.9 fps** in
  eating, disgusted and resting, no JS errors.
- Screenshots: `reports/redesign_screenshots/` (states, Top view with Sugar selected,
  Follow view, dashboard at 390 px, phone page).

## Decisions

1. **flybody instead of NeuroMechFly.** Both are open scanned-fly models (Apache-2.0). The
   reference image matches flybody (tan body, red eyes, bristles, veined wings), and flybody
   has separate meshes per material and a full joint tree, so it can be posed.
2. **Built, not committed.** The GLBs are derived from a 140 MB download, so they live in the
   gitignored `data/` and are built by `python -m server.fly_model`, like the connectome
   data. Without them the page falls back to the primitive fly. Added `fast-simplification`
   (build-time only) to `requirements.txt`.
3. **Two levels of detail.** With the full model, the live validation failed under
   SwiftShader (20 fps, 15.8 Hz ticks: the software renderer and the simulator compete for
   the CPU). The low model (quarter of the triangles, no bristles, Lambert shading), a thinner
   backdrop in low quality (every 5th neuron) and no `preserveDrawingBuffer` brought it back
   to passing. No threshold was changed.
4. **Whole brain as backdrop, clearly marked.** Drawing only the 17,101 simulated neurons
   left the optic lobes empty and the shape hard to read. The full annotation table gives the
   reference's look; the count line, the dim color, the tooltip and a note under the panels
   all say which neurons are simulated.
5. **Joint angles by looking.** The proboscis (tucked 0.8/0.8, out −0.8/−1.2 rad), the
   grooming pose and the folded wings (the model's spring rest angles) were found by
   rendering poses, not taken from a paper.
6. **Droplet height.** The extended labellum ends about 0.55 mm above the floor, so the drop is
   a 0.5 mm-high bead. A real fly would also lower its body; bending all six legs was left out.

## Open problems

- Under SwiftShader the fps sits exactly at the 30 fps line (as it did before this change);
  one run during development measured 29.9 and failed. On a real GPU it is 60.
- No walking: the brain model has no locomotion output, so the fly never walks (the
  reference's "Walking backward" state has no counterpart here).
- The camera tabs are hidden when the primitive fallback fly is shown.
- The dark threshold difference between phone (0.15) and dashboard (0.3) is still open.

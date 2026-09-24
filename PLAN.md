# Fly Tamagotchi: Project Plan

## Concept

A virtual fruit fly pet whose decisions come from a real fly brain wiring diagram (connectome). The iPhone is the controller: tap to give sugar, shake to give something bitter, cover the camera to make it dark. The laptop runs the brain simulation and shows the fly, its mood, and the neurons lighting up.

**Core rule:** The fly only "eats" if its simulated feeding neurons actually fire. Feeding behavior must come from the brain, not from hard-coded game logic.

## Brain-Driven vs Game-Driven

Be honest about which parts come from the connectome and which are game rules.

| Behavior | Source |
|---|---|
| Eating (MN9 firing) | **Brain** |
| Eating less when bitter is present | **Brain** |
| Neuron activity shown in 3D view | **Brain** |
| Light input changing visual neuron activity | **Brain** (if suitable input neurons exist in the data) |
| Hunger rising over time | Game rule |
| Energy restored in darkness | Game rule (the model has no sleep circuit) |
| Happiness | Game rule, fed by brain outputs (eating, bitter neuron activity) |
| Fainting | Game rule |

Optional brain link: hunger can scale the sugar input firing rate (hungry fly = stronger sugar signal). This lets the game state affect the brain without coding the behavior directly.

## Architecture

```
iPhone (Safari web page)  ──WebSocket──►  Laptop Python server  ──►  Brain simulation
  tap / shake / camera                     (FastAPI)                  (sparse LIF model)
                          ◄──────────────  game state + mood  ◄──────  spike output
                                              │
                                              ▼
                                     Laptop dashboard page
                                     (fly + mood bars + 3D brain)
```

## Tech Stack

| Part | Choice |
|---|---|
| Brain model | Leaky integrate-and-fire (LIF) model built from FlyWire connectome data, based on Shiu et al. 2024 (GitHub: `philshiu/Drosophila_brain_model`) |
| Simulation | NumPy / SciPy sparse matrices (PyTorch if a GPU is available) |
| Server | Python, FastAPI, WebSockets |
| Phone page | Plain HTML/JS: touch events, DeviceMotion (shake), camera (brightness), vibration |
| Dashboard | HTML/JS with three.js for the 3D brain point cloud |
| HTTPS | mkcert or ngrok (Safari requires HTTPS for motion and camera access) |

## Folder Layout

```
fly-tamagotchi/
├── PLAN.md
├── CLAUDE.md       # working rules for Claude Code
├── brain/          # data loading, weight matrix, LIF simulator, neuron groups
├── server/         # FastAPI app, WebSocket handlers, game loop, config
├── web/
│   ├── phone/      # iPhone controller page
│   └── dashboard/  # fly display, mood bars, 3D brain
├── tests/          # unit tests, behavior tests, shuffled-brain control
└── data/           # downloaded connectome files (gitignored)
```

---

## Phase 1: Brain Works Offline (no phone yet)

1. Download the FlyWire connectivity and neuron annotation files used by the Shiu et al. model. **Use the same data release version as the repo** and record it in the README.
2. Build a signed sparse weight matrix: synapse count × sign from predicted neurotransmitter, matching the repo's convention.
3. Take LIF parameters from the repo's code, not from memory. Keep them in one config with the source cited.
4. Write a fast LIF simulator that steps in small chunks (e.g., 50 ms) and keeps its state between chunks so it can run live.
5. Define neuron groups by looking them up in the data files (do not hard-code guessed IDs). Save them to `data/neuron_groups.json` with the source of each lookup:
   - Sugar taste neurons
   - Bitter taste neurons
   - Feeding motor neurons (MN9)
   - Light input neurons: FlyWire coverage of photoreceptors may be partial. Report which visual input neurons actually exist (e.g., R7/R8, ocellar) before choosing. If none are usable, say so; light can fall back to a game-only input.
6. **Validate before moving on** (at least 5 random seeds each, report mean ± SD firing rates):
   - Sugar input → MN9 fires
   - Sugar + bitter → MN9 firing is reduced
   - Shuffled brain does NOT reproduce these results. Shuffle = keep the same neurons, the same number of connections, and the same weight values, but randomize which neuron each connection targets.
   - Sanity check: our sugar → MN9 result roughly matches the repo's own published result.
7. **Measure speed:** wall-clock time per 50 ms of simulated time. Real-time needs under 50 ms.

**Done when:** All validation tests pass across seeds, and the speed number is reported (even if too slow; that gets solved before Phase 2).

## Phase 2: Server

1. If Phase 1 was too slow for real time, first build a reduced circuit (neurons within a few connection steps of inputs and outputs) and re-run the Phase 1 tests on it.
2. FastAPI app with two WebSocket endpoints: `/ws/phone` and `/ws/dashboard`.
3. Background loop runs the brain continuously with light background noise.
4. Incoming phone events set input firing rates (e.g., "sugar on for 2 seconds").
5. Broadcast to the dashboard at a capped rate (about 10–20 updates per second):
   - Spike counts per neuron group
   - A limited sample of spiking neuron IDs for the 3D view (e.g., max 500 per update)
   - Current game state and mood values

**Done when:** A test script can send fake phone events and receive changing spike counts.

## Phase 3: iPhone Controller Page

1. Large tap zone = give sugar.
2. Shake detection with DeviceMotion, including the iOS "Allow motion access" button.
3. Camera brightness check a few times per second; dark = reduce light input.
4. Show the fly's mood on the phone and vibrate when the fly eats.
5. Dashboard shows a QR code so the phone can connect quickly.

**Done when:** All three inputs work on a real iPhone over HTTPS.

## Phase 4: Laptop Dashboard

1. Simple 2D cartoon fly with states: idle, eating, disgusted, resting in the dark.
2. Mood bars:
   - **Hunger** (rises slowly over time)
   - **Happiness**
   - **Energy**
3. 3D brain: neuron positions as dots; spiking neurons flash, colored by group.
4. Live activity chart for sugar, bitter, and MN9 groups.

**Done when:** The dashboard updates smoothly in real time from server data.

## Phase 5: Game Rules

1. Hunger rises over time and only goes down when MN9 firing passes a threshold.
2. Bitter lowers happiness. Reduced eating must come from the brain, not a coded rule.
3. Darkness slowly restores energy; too much light while tired lowers happiness. (Game rule, see table above.)
4. If hunger stays maxed out too long, the fly faints (reset button to revive).
5. Optional: hunger scales the sugar input rate.
6. Keep all rule values in one config file (`server/config.py` or `config.yaml`).

**Done when:** A full play session feels responsive and the rules are easy to tweak.

## Phase 6: Testing

1. **Unit tests:** matrix building, neuron group lookups, event handling.
2. **Behavior tests:** sugar → eating, bitter → less eating, compared against a shuffled brain.
3. **Timing test:** phone tap to fly reaction under ~300 ms.
4. **Real iPhone test:** permissions, shake sensitivity, camera brightness in different rooms.

## Phase 7: Classroom Polish (optional)

1. "Brain view" toggle explaining in simple words what each lit-up region does.
2. Multiplayer mode: several phones, each controlling one sense.
3. "Brain surgery" panel with switches to turn neuron groups off and watch behavior change.

---

## Notes and Limitations

- The connectome gives wiring only. Connection strength is estimated from synapse counts, and excitation/inhibition is inferred from predicted neurotransmitters.
- The wiring is fixed, so the fly cannot learn.
- The full brain (~130,000+ neurons) may not run in real time on a laptop; a reduced circuit is acceptable for live play.
- Energy, hunger, and fainting are game rules. Only feeding and neuron activity come from the brain.
- Always keep the shuffled-brain control: if a randomly rewired brain behaves the same, the behavior is coming from the setup, not the real wiring.

## Working With Claude Code

Working rules are in `CLAUDE.md`. Build one phase at a time, plan first, and stop for review after each phase.
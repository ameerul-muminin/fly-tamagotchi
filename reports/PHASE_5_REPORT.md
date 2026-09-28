# Phase 5 Report: Game Rules

**Status: done.** `pytest -q`: 96 passed. `python -m server.validate_game`: all 7 checks pass
on the reduced brain, 5 seeds. The dashboard validator's replay checks pass; its live
speed checks failed in the last run while a second brain (the user's own server) was
running on the same machine; see "Open problems".

Plan: `reports/PHASE_5_PLAN.md` (thresholds fixed there before the first run).

## What was built

| Part | Files | What it does |
|---|---|---|
| Rules | `server/game.py` | Pure `step(state, dt, eating, bitter_hz, light)`: hunger, happiness, energy, fainting; `revive`; `sugar_rate_hz` (the one game → brain link). |
| Values | `server/config.py` `GameRules` | Every rule value in one place, including the single dark threshold (0.15) that the phone page now also uses. |
| Server | `server/brain_runner.py`, `server/app.py` | Steps the rules after every 50 ms chunk from that chunk's readouts; scales the sugar input rate by hunger; `revive` message; `reset_brain` also starts a fresh fly; `hello.brain.game_rules`; `game.dark`, `fainted`, `starving_s`, `mood_rules_active: true`. |
| Dashboard | `state.js`, `fly_motion.js`, `fly_model3d.js`, `main.js`, `index.html`, `style.css`, `fly.js` | New top-priority state **fainted** (the fly rolls onto its back, legs curled) with a **Revive** button; resting from the server's `game.dark`; the state tag says **game rule** for fainted and resting and **brain decides** for eating and disgust; "Why" text for a full fly and a fainted fly; mood note with a faint countdown while starving. |
| Phone | `controller.js`, `phone.js`, `phone.css` | Uses the server's `dark`; shows "Fainted! Revive it on the laptop" and "Hungry! Tap for sugar". |
| Validation | `server/validate_game.py`, `GameChecks` | G1–G7 on the real reduced brain. |
| Tests | `tests/test_game.py` (15), additions in `test_server.py`, `controller.test.mjs`, `state.test.mjs`, `fun.test.mjs` | Rules without a brain, server wiring, pages. |
| Sample | `web/dashboard/samples/session.jsonl` | Re-recorded with the Phase 5 server (372 ticks), so replays carry the new fields. |

## Golden rule

- Hunger falls **only** in chunks where the MN9 readout says eating (G1: 2,073 of 2,073 such
  chunks across 5 seeds).
- No rule reads the bitter **input**. Happiness reads bitter-neuron **spikes**; nothing
  touches eating. Unit test: a fly the brain says is eating loses exactly the same hunger with
  or without bitter spikes.
- Satiety is not a rule. Hunger scales the sugar input rate (PLAN.md's optional item), and the
  connectome decides whether MN9 still fires.

## Results (`python -m server.validate_game`, reduced brain, seeds 0–4, 214.7 s)

| Check | Result (mean ± SD, 5 seeds) | Threshold | |
|---|---|---|---|
| G1 hunger falls only while eating | 100 % of falling chunks were eating chunks, every seed | 100 % | PASS |
| G2 a hungry fly eats (start 0.9, sugar on) | hunger −0.778 ± 0.021 in 20 s | ≥ 0.3 | PASS |
| G3 satiety from the brain | eating 6.6 ± 1.5 % of the last 20 s; final hunger 0.114 ± 0.009 | ≤ 25 %; 0.03–0.35 | PASS |
| G4 control, scaling off | eating 100 ± 0 % of the last 20 s; hunger 0.000 | ≥ 75 % | PASS |
| G5 bitter lowers happiness (3 s) | −0.150 ± 0.000 | ≥ 0.1 | PASS |
| G6 sugar + bitter vs sugar (hunger 0.9) | MN9 3.2 ± 1.9 Hz vs 76.6 ± 2.7 Hz | lower, every seed | PASS |
| G7 dark restores energy (10 s) | +0.250 ± 0.000 | ≥ 0.2 | PASS |

Per seed (seed: final hunger, sugar rate at the end, hunger when eating first stopped):
0: 0.108, 42.9 Hz, 0.086 · 1: 0.103, 42.3 Hz, 0.104 · 2: 0.125, 45.0 Hz, 0.117 ·
3: 0.115, 43.8 Hz, 0.138 · 4: 0.118, 44.1 Hz, 0.143.

**The prediction held.** Before any rule was written, a sweep of the reduced brain put MN9's
eating-line crossing at about 47 Hz of sugar input, which predicts satiety at hunger ≈ 0.14 and
about 8 % eating time afterwards. Measured: the fly first stopped at hunger 0.118 ± 0.024,
settled near 0.114 with the sugar drive at 43.6 ± 1.1 Hz, and then nibbled 6.6 % of the time.
With scaling off, the same fly ate until hunger reached 0 and kept going.

G5 and G7 have SD 0 because they depend only on the rule rates (3 s × 0.05, 10 s × 0.025):
bitter GRNs fire at 150 Hz input in every seed, above the 20 Hz line throughout.

## Decisions

1. **Hunger scales sugar (optional item) is on by default.** It is the only honest way to get
   satiety without a "full → don't eat" rule. `hunger_scales_sugar=False` switches it off.
2. **One dark threshold, 0.15** (the phone's, which worked in the real-iPhone test), sent by
   the server as `game.dark`. The dashboard's old 0.3 remains only as the fallback for
   recordings without `dark`.
3. **Revive = start values; `reset_brain` also revives.** A reset is a new session. Revive
   alone leaves the brain running.
4. **Fainting freezes the mood**, and the phone's inputs still reach the brain (nothing
   gates the connectome); only the display and mood stop.
5. **Two older tests changed with the message contract**, not their thresholds:
   `test_phone_receives_status` asserted the Phase 2 placeholder `mood_rules_active is False`
   (now `True`, plus the new fields), and `test_recorded_sample_follows_the_message_format`
   pins the exact `game` keys (three added). Both are documented in `MESSAGE_FORMAT.md`.
6. **Rule rates are first guesses for a few-minute session** (starving in 4 min, full meal in
   ~15 s of eating, faint after 30 s at 100 %). They are all in `GameRules`.

## Open problems

1. **Dashboard live speed check with a second brain running.** The last
   `validate_dashboard` run: replay 11/11 PASS; live tick rate 14.9 Hz (needs 18) and 20 fps
   (needs 30) FAIL. During that run the user's own server (`python -m server`, PID 40748,
   ~560 s CPU) was running its brain loop on the same CPU, next to the validator's brain and
   software rendering. The two runs before it, without that server, passed all checks
   (20.1 and 20.2 Hz, 30.0 fps). Phase 5 adds one small function call per 50 ms chunk.
   To confirm, rerun `python -m server.validate_dashboard` with no other server running.
2. **Not play-tested by a person.** "Feels responsive" (PLAN.md's done-criterion) needs a real
   session with the phone; the rates may need tuning.
3. **Happiness has no upper-level effect yet** (nothing happens at 0 or 1). PLAN.md does not
   ask for one.
4. The project guide PDF (`reports/FLY_TAMAGOTCHI_GUIDE.pdf`) still describes the mood as a
   placeholder.

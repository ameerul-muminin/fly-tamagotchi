# Phase 5 Plan: Game Rules

Goal (PLAN.md Phase 5): hunger, happiness and energy become real game rules; the fly can
faint; every rule value lives in one config. Done when a play session feels responsive and
the rules are easy to tweak.

## Golden rule

The rules may read brain **outputs** (the MN9 eating readout, bitter-neuron spikes) and game
inputs (time, light). They never decide whether the fly eats. The one link from the game into
the brain is PLAN.md's optional item: hunger scales the **sugar input rate**, i.e. how hard
the phone's sugar drives the sugar GRNs. Whether MN9 then fires is still up to the
connectome.

## Measurement that shapes the design (before any rule was written)

Reduced brain, sugar input only, 1 s trials, 5 seeds (scratch sweep, `brain.validate.run_trial`):

| Sugar input | MN9 (mean ± SD) |
|---|---|
| 30 Hz | 0.2 ± 0.4 Hz |
| 50 Hz | 23.6 ± 4.1 Hz |
| 60 Hz | 39.2 ± 6.1 Hz |
| 75 Hz | 52.6 ± 8.2 Hz |
| 90 Hz | 65.4 ± 7.0 Hz |
| 120 Hz | 78.0 ± 7.2 Hz |
| 150 Hz | 84.2 ± 4.9 Hz |

MN9 crosses the 20 Hz eating line between 30 and 50 Hz of input. So with the sugar rate
scaled from 30 Hz (hunger 0) to 150 Hz (hunger 1), a sated fly's sugar signal is too weak for
MN9 to pass the line: the fly stops eating by itself, through the brain. No "full → don't
eat" rule is needed or written. Expected satiety point: MN9 crosses 20 Hz near 47 Hz input
(linear between 30 and 50 Hz), i.e. hunger ≈ 0.14. Because hunger creeps back up, the fly
should then nibble now and then: at equilibrium about 0.0042 / (0.05 + 0.0042) ≈ 8 % of the
time eating, which is why G3 tests an eating fraction rather than "never eats again".

## Rules (all in `server/config.py`, `GameRules`)

| Rule | Reads | Value |
|---|---|---|
| Hunger rises | time | +1/240 per s (empty to starving in 4 min) |
| Hunger falls | `game.eating` (MN9 ≥ 20 Hz over 500 ms, brain) | −0.05 per s of eating |
| Happiness up | `game.eating` | +0.03 per s |
| Happiness down: bitter | bitter GRN rate ≥ 20 Hz in the tick (brain spikes) | −0.05 per s |
| Happiness down: starving | hunger ≥ 0.8 | −0.01 per s |
| Happiness down: light while tired | not dark and energy < 0.3 | −0.02 per s |
| Energy | light level | −1/300 per s in light, +1/40 per s in the dark |
| Dark | phone light level < `dark_below` | 0.15 (one value for server, phone and dashboard) |
| Faint | hunger at 1.0 | after 30 s at 1.0; mood freezes until revived |
| Revive | dashboard "Revive" (`revive`) or "Reset brain" | mood back to the start values |
| Sugar drive (optional link) | hunger | sugar rate = 150 Hz × (0.2 + 0.8 × hunger) |
| Start values | | hunger 0.5, happiness 0.7, energy 1.0 |

The rules live in `server/game.py` as a pure function of (state, dt, readouts), so they are
unit-tested without a brain.

## Messages

- `tick.game` / `status`: `mood_rules_active: true`, plus `dark`, `fainted`,
  `starving_s` (time at hunger 1.0).
- `hello.brain.game_rules`: the rule values, so the pages show the real numbers.
- Dashboard → server: `{"type": "revive"}`.
- `inputs_hz.sugar` already reports the scaled rate.

## Pages

- Dashboard: live mood bars; a "fainted" fly state (top priority) with a Revive button in
  the fly viewer; "resting" from `game.dark` (the server's single threshold); the "Why"
  text explains a full fly ("sugar input scaled down to N Hz: too weak for MN9").
- Phone: "Fainted, revive it on the laptop"; dark from `status.dark`.

## Validation (`python -m server.validate_game`, reduced brain, not paced to real time)

Thresholds fixed here, before the first run, in `server/config.py` `GameChecks`:

| Check | Pass if |
|---|---|
| G1 hunger falls only while eating | in every tick where hunger went down, `game.eating` was true (100 %), all 5 seeds |
| G2 a hungry fly eats | start hunger 0.9 with continuous sugar: hunger falls by ≥ 0.3 within 20 s, all 5 seeds |
| G3 satiety comes from the brain | same run, 60 s: eating fraction in the last 20 s ≤ 25 % and final hunger between 0.03 and 0.35, all 5 seeds; report mean ± SD |
| G4 control: no scaling, no satiety | same run with `hunger_scales_sugar=False`: eating fraction in the last 20 s ≥ 75 %, all 5 seeds |
| G5 bitter lowers happiness | 3 s of bitter: happiness falls by ≥ 0.1, all 5 seeds |
| G6 sugar + bitter: brain reduces eating | mean MN9 during sugar+bitter < mean MN9 during sugar alone at the same hunger, all 5 seeds |
| G7 dark restores energy | 10 s dark after starting at energy 0.5: energy rises by ≥ 0.2 |

Unit tests (`tests/test_game.py`) cover faint timing, revive, freezing while fainted,
clamping to [0, 1], "bitter never touches hunger or eating", and the sugar-rate formula.

## Out of scope

Phase 6 (timing test), Phase 7. No change to the brain, LIF parameters or eating readout.

"""Phase 5 game rules: hunger, happiness, energy and fainting.

Pure functions of (state, elapsed time, readouts), so tests run them without a brain.
All values come from `server.config.GameRules`.

What the rules read:
- `eating`: the MN9 readout (mean MN9 rate over the eating window >= threshold). It comes
  from simulated spikes; the rules only react to it.
- `bitter_hz`: the bitter GRNs' firing rate in the tick (spikes, not the phone input).
- `light`: the phone camera's level (a game input; light is not wired into this brain).

What they never do: decide whether the fly eats, or treat bitter as "eat less". The one
game -> brain link is `sugar_rate_hz`: hunger sets the sugar input's Poisson rate, and the
connectome decides what MN9 does with it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from server.config import GameRules


@dataclass
class GameState:
    """Mood and flags of the fly. Mood values are in [0, 1]."""

    hunger: float
    happiness: float
    energy: float
    fainted: bool = False
    starving_s: float = 0.0     # time spent at hunger 1.0 (resets below it)

    @classmethod
    def start(cls, rules: GameRules) -> "GameState":
        return cls(rules.start_hunger, rules.start_happiness, rules.start_energy)

    def mood(self) -> dict[str, float]:
        return {"hunger": self.hunger, "happiness": self.happiness, "energy": self.energy}


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def is_dark(light: float, rules: GameRules) -> bool:
    """The phone's light level counts as dark below `dark_below`."""
    return light < rules.dark_below


def step(s: GameState, dt_s: float, *, eating: bool, bitter_hz: float, light: float,
         rules: GameRules) -> GameState:
    """Advance the rules by `dt_s` seconds. Returns a new state.

    A fainted fly's mood is frozen until `revive`.
    """
    if s.fainted or dt_s <= 0:
        return GameState(**asdict(s))
    r = rules
    dark = is_dark(light, r)

    hunger = s.hunger + r.hunger_rise_per_s * dt_s
    if eating:
        hunger -= r.hunger_eat_per_s * dt_s

    happy = s.happiness
    if eating:
        happy += r.happy_eat_per_s * dt_s
    if bitter_hz >= r.bitter_hz:
        happy -= r.unhappy_bitter_per_s * dt_s
    if s.hunger >= r.starving_at:
        happy -= r.unhappy_starving_per_s * dt_s
    if not dark and s.energy < r.tired_below:
        happy -= r.unhappy_light_tired_per_s * dt_s

    energy = s.energy + (r.energy_dark_per_s if dark else r.energy_light_per_s) * dt_s

    hunger = _clamp(hunger)
    starving_s = s.starving_s + dt_s if hunger >= 1.0 else 0.0
    return GameState(hunger, _clamp(happy), _clamp(energy),
                     fainted=starving_s >= r.faint_after_s, starving_s=starving_s)


def revive(rules: GameRules) -> GameState:
    """A fresh fly (dashboard "Revive" and "Reset brain")."""
    return GameState.start(rules)


def sugar_rate_hz(base_hz: float, hunger: float, rules: GameRules) -> float:
    """Poisson rate for the sugar GRNs while sugar is on: stronger when hungry.

    Without `hunger_scales_sugar` it is always `base_hz`.
    """
    if not rules.hunger_scales_sugar:
        return base_hz
    return base_hz * (rules.sugar_min_frac + (1.0 - rules.sugar_min_frac) * _clamp(hunger))


def rules_info(rules: GameRules) -> dict:
    """The rule values, sent in `hello.brain.game_rules` so pages show the real numbers."""
    return asdict(rules)

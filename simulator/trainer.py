"""Trainer agent — all decision-making lives here."""

from __future__ import annotations

import math
import random
from collections import namedtuple
from typing import Union

from simulator.move import Move
from simulator.pokemon import Pokemon
from simulator.type_chart import get_effectiveness, weather_modifier
from simulator.items import get_item_data


# Shared state snapshot passed to choose_action each turn.
# t1 and t2 are Trainer objects; weather is a str or None; turn is an int.
BattleState = namedtuple("BattleState", ["t1", "t2", "weather", "turn"])

# An action is either a Move to use or an int (team index to switch to).
Action = Union[Move, int]


class Trainer:
    """Wraps a Pokémon team and a move-selection strategy."""

    def __init__(
        self,
        name: str,
        team: list[Pokemon],
        strategy: str = "greedy",
    ) -> None:
        self.name = name
        self.team = team
        self.strategy = strategy
        self.active_index: int = 0
        self.choice_lock: str | None = None  # set by Choice items; cleared on switch

    @property
    def active(self) -> Pokemon:
        return self.team[self.active_index]

    def alive_bench_indices(self) -> list[int]:
        """Indices of alive, non-active team members."""
        return [
            i for i, p in enumerate(self.team)
            if i != self.active_index and not p.is_fainted
        ]

    def is_defeated(self) -> bool:
        return all(p.is_fainted for p in self.team)

    def choose_action(self, battle_state: BattleState) -> Action:
        """Return a Move to use or a team index to switch to."""
        # Enforce Choice lock: must use that move or switch out
        if self.choice_lock:
            locked = next(
                (m for m in self.active.moveset if m.name == self.choice_lock), None
            )
            if locked:
                return locked
            else:
                self.choice_lock = None  # stale lock (different Pokémon active), clear

        if self.strategy == "random":
            return self._random_action()
        elif self.strategy == "greedy":
            return self._greedy_action(battle_state)
        elif self.strategy == "minimax":
            return self._minimax_action(battle_state)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy!r}")

    # ------------------------------------------------------------------
    # Strategy: random
    # ------------------------------------------------------------------

    def _random_action(self) -> Action:
        bench = self.alive_bench_indices()
        if bench and random.random() < 0.15:
            return random.choice(bench)
        return random.choice(self.active.moveset)

    # ------------------------------------------------------------------
    # Strategy: greedy
    # ------------------------------------------------------------------

    def _greedy_action(self, battle_state: BattleState) -> Action:
        """Best expected-damage move. Proactively switch out of bad matchups."""
        opp = _opponent(self, battle_state).active

        scores = [(_move_score(m, self.active, opp), m) for m in self.active.moveset]
        best_score = max(s for s, _ in scores)

        bench = self.alive_bench_indices()

        # If completely walled (immune / only resisted moves), try to find a better matchup
        if bench:
            current_best_eff = max(
                get_effectiveness(m.type, opp.types)
                for m in self.active.moveset
                if m.power is not None
            ) if any(m.power for m in self.active.moveset) else 0.0

            if current_best_eff < 1.0:
                for i in bench:
                    bench_mon = self.team[i]
                    bench_eff = max(
                        (get_effectiveness(m.type, opp.types) for m in bench_mon.moveset if m.power),
                        default=0.0,
                    )
                    if bench_eff >= 2.0:
                        return i  # switch to a counter

        if best_score == 0:
            return random.choice(self.active.moveset)

        best_moves = [m for s, m in scores if s == best_score]
        return random.choice(best_moves)

    # ------------------------------------------------------------------
    # Strategy: minimax (depth-2 expectiminimax, deterministic via EV)
    # ------------------------------------------------------------------

    def _minimax_action(self, battle_state: BattleState) -> Action:
        """
        Enumerate all (my_action × opp_action) pairs at depth 1.
        For each pair, compute expected post-turn score.
        Return the action that maximises the minimum opponent response.
        """
        opp_trainer = _opponent(self, battle_state)
        my_actions = _available_actions(self)
        opp_actions = _available_actions(opp_trainer)

        best_action: Action = my_actions[0]
        best_score = float("-inf")

        for my_action in my_actions:
            # Worst-case opponent response (minimax = max of min)
            worst = float("inf")
            for opp_action in opp_actions:
                score = _simulate_pair_score(
                    self, my_action, opp_trainer, opp_action, battle_state
                )
                if score < worst:
                    worst = score
            if worst > best_score:
                best_score = worst
                best_action = my_action

        return best_action

    def __repr__(self) -> str:
        alive = sum(1 for p in self.team if not p.is_fainted)
        return (
            f"Trainer({self.name!r}, strategy={self.strategy!r}, "
            f"active={self.active.name!r}, alive={alive}/{len(self.team)})"
        )


# ------------------------------------------------------------------
# Minimax helpers (module-level to keep Trainer clean)
# ------------------------------------------------------------------

def _opponent(trainer: Trainer, state: BattleState) -> Trainer:
    return state.t2 if state.t1 is trainer else state.t1


def _available_actions(trainer: Trainer) -> list[Action]:
    return list(trainer.active.moveset) + trainer.alive_bench_indices()


def _move_score(move: Move, attacker: Pokemon, defender: Pokemon) -> float:
    """Heuristic expected damage score for greedy/minimax evaluation."""
    if move.power is None:
        # Status moves: score based on their secondary effect potential
        if any("stat" in e and e.get("target") == "self" for e in move.secondary):
            return 15.0  # setup moves are valuable
        if any("inflict" in e for e in move.secondary):
            return 10.0  # status-inflicting moves are useful
        return 0.0
    stab = 1.5 if move.type in attacker.types else 1.0
    eff = get_effectiveness(move.type, defender.types)
    acc = (move.accuracy / 100) if move.accuracy is not None else 1.0
    item_data = get_item_data(attacker.held_item)
    item_mult = 1.0
    if move.category == "physical":
        item_mult = item_data.get("physical_damage_mult", item_data.get("damage_mult", 1.0))
    else:
        item_mult = item_data.get("special_damage_mult", item_data.get("damage_mult", 1.0))
    return move.power * stab * eff * acc * item_mult


def _expected_damage(
    attacker: Pokemon,
    defender: Pokemon,
    move: Move,
    weather: str | None,
) -> float:
    """Deterministic expected damage (mean roll = 0.925, no crit)."""
    if move.power is None:
        return 0.0

    if move.category == "physical":
        a_stat = attacker.effective_stat("atk")
        d_stat = defender.effective_stat("def_")
        if attacker.status == "burn":
            a_stat = math.floor(a_stat / 2)
    else:
        a_stat = attacker.effective_stat("sp_atk")
        d_stat = defender.effective_stat("sp_def")

    base = math.floor(
        math.floor(math.floor(2 * attacker.level / 5 + 2) * move.power * a_stat / d_stat / 50) + 2
    )

    stab = 1.5 if move.type in attacker.types else 1.0
    eff = get_effectiveness(move.type, defender.types)
    acc = (move.accuracy / 100) if move.accuracy is not None else 1.0
    w_mod = weather_modifier(move.type, weather)

    item_data = get_item_data(attacker.held_item)
    if move.category == "physical":
        item_mult = item_data.get("physical_damage_mult", item_data.get("damage_mult", 1.0))
    else:
        item_mult = item_data.get("special_damage_mult", item_data.get("damage_mult", 1.0))

    return base * stab * eff * acc * w_mod * item_mult * 0.925


def _simulate_pair_score(
    me: Trainer,
    my_action: Action,
    opp: Trainer,
    opp_action: Action,
    state: BattleState,
) -> float:
    """
    Estimate the board score after both trainers take their action.
    Score = (my_team_hp_frac - opp_team_hp_frac) + 0.25 * matchup_advantage
    """
    # Which Pokémon will be active after potential switches?
    my_active = me.team[my_action] if isinstance(my_action, int) else me.active
    opp_active = opp.team[opp_action] if isinstance(opp_action, int) else opp.active

    # Expected damage dealt this turn
    my_dmg = 0.0
    opp_dmg = 0.0

    if isinstance(my_action, Move) and my_action.power is not None:
        my_dmg = _expected_damage(my_active, opp_active, my_action, state.weather)

    if isinstance(opp_action, Move) and opp_action.power is not None:
        opp_dmg = _expected_damage(opp_active, my_active, opp_action, state.weather)

    # Projected HP after this turn
    my_hp_after = max(0.0, my_active.current_hp - opp_dmg)
    opp_hp_after = max(0.0, opp_active.current_hp - my_dmg)

    # Team-level HP fractions
    my_total_max = sum(p.hp for p in me.team)
    opp_total_max = sum(p.hp for p in opp.team)
    my_total_cur = sum(p.current_hp for p in me.team)
    opp_total_cur = sum(p.current_hp for p in opp.team)

    # Adjust for the projected damage delta on the active Pokémon
    my_hp_frac = (my_total_cur - (my_active.current_hp - my_hp_after)) / my_total_max
    opp_hp_frac = (opp_total_cur - (opp_active.current_hp - opp_hp_after)) / opp_total_max

    # Matchup bonus: log2-based type advantage score
    my_best_eff = max(
        (get_effectiveness(m.type, opp_active.types) for m in my_active.moveset if m.power),
        default=1.0,
    )
    opp_best_eff = max(
        (get_effectiveness(m.type, my_active.types) for m in opp_active.moveset if m.power),
        default=1.0,
    )
    my_adv = math.log2(my_best_eff) / 2 if my_best_eff > 0 else -1.0
    opp_adv = math.log2(opp_best_eff) / 2 if opp_best_eff > 0 else -1.0

    return (my_hp_frac - opp_hp_frac) + 0.25 * (my_adv - opp_adv)

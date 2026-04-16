"""Trainer agent — holds team, genome, and bag. Routes decisions to policies.py."""

from __future__ import annotations

import copy
from collections import namedtuple
from typing import Union

from simulator.genome import FamilyType, Genome
from simulator.items import ItemUse
from simulator.move import Move
from simulator.pokemon import Pokemon

# Shared state snapshot passed to choose_action each turn.
BattleState = namedtuple("BattleState", ["t1", "t2", "weather", "turn"])

# An action is a Move to use, a team index to switch to, or a bag item to use.
Action = Union[Move, int, ItemUse]

_DEFAULT_BAG: dict[str, int] = {}


class Trainer:
    """Wraps a Pokémon team, a family identity, a genome, and a bag of consumable items."""

    def __init__(
        self,
        name: str,
        team: list[Pokemon],
        family: FamilyType,
        genome: Genome,
        bag: dict[str, int] | None = None,
    ) -> None:
        self.name = name
        self.team = team
        self.family = family
        self.genome = genome
        self._initial_bag: dict[str, int] = dict(bag) if bag else {}
        self.bag: dict[str, int] = dict(self._initial_bag)

        self.active_index: int = 0
        self.choice_lock: str | None = None
        self._last_hp: int = -1  # stall policy reads this to detect damage taken last turn

    @property
    def active(self) -> Pokemon:
        return self.team[self.active_index]

    def alive_bench_indices(self) -> list[int]:
        """Indices of alive, non-active team members."""
        return [
            bench_index
            for bench_index, pokemon in enumerate(self.team)
            if bench_index != self.active_index and not pokemon.is_fainted
        ]

    def is_defeated(self) -> bool:
        return all(pokemon.is_fainted for pokemon in self.team)

    def choose_action(self, battle_state: BattleState) -> Action:
        """Route to the appropriate policy function based on family."""
        from simulator import policies

        # Enforce Choice lock: must use that move or switch out
        if self.choice_lock:
            locked_move = next(
                (m for m in self.active.moveset if m.name == self.choice_lock), None
            )
            if locked_move:
                return locked_move
            else:
                self.choice_lock = None  # stale lock (Pokémon switched), clear it

        if self.family == FamilyType.GREEDY:
            return policies.greedy_policy(self, battle_state, self.genome)
        if self.family == FamilyType.STALL:
            return policies.stall_policy(self, battle_state, self.genome)
        if self.family == FamilyType.SETUP:
            return policies.setup_policy(self, battle_state, self.genome)
        if self.family == FamilyType.RANDOM:
            return policies.random_policy(self, battle_state, self.genome)

        # Minimax is handled as a special case — no genome
        from simulator.policies import minimax_policy
        return minimax_policy(self, battle_state)

    def choose_replacement(self, battle_state: BattleState) -> int:
        """Return the bench index to send in after a faint — policy-specific logic."""
        from simulator import policies

        if self.family == FamilyType.GREEDY:
            return policies.greedy_replacement(self, battle_state)
        if self.family == FamilyType.STALL:
            return policies.stall_replacement(self, battle_state)
        if self.family == FamilyType.SETUP:
            return policies.setup_replacement(self, battle_state)
        if self.family == FamilyType.RANDOM:
            return policies.random_replacement(self, battle_state)

        # Minimax falls back to greedy replacement logic
        return policies.greedy_replacement(self, battle_state)

    def reset_bag(self) -> None:
        """Restore the bag to its initial contents (called between battles)."""
        self.bag = dict(self._initial_bag)

    def __repr__(self) -> str:
        alive_count = sum(1 for pokemon in self.team if not pokemon.is_fainted)
        return (
            f"Trainer({self.name!r}, family={self.family.value!r}, "
            f"active={self.active.name!r}, alive={alive_count}/{len(self.team)})"
        )

"""Trainer agent — all decision-making lives here."""

from __future__ import annotations

import random
from typing import Literal

from simulator.move import Move
from simulator.pokemon import Pokemon
from simulator.type_chart import get_effectiveness


Strategy = Literal["random", "greedy"]


class Trainer:
    """Wraps a Pokémon and a move-selection strategy."""

    def __init__(self, name: str, pokemon: Pokemon, strategy: Strategy = "greedy") -> None:
        self.name = name
        self.pokemon = pokemon
        self.strategy = strategy

    # ------------------------------------------------------------------
    # Public interface used by Battle
    # ------------------------------------------------------------------

    def choose_move(self, opponent: Pokemon) -> Move:
        """Select a move given the current opponent."""
        if self.strategy == "random":
            return self._random_move()
        elif self.strategy == "greedy":
            return self._greedy_move(opponent)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy!r}")

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _random_move(self) -> Move:
        return random.choice(self.pokemon.moveset)

    def _greedy_move(self, opponent: Pokemon) -> Move:
        """Pick the move with the highest expected damage.

        Expected damage ∝ power × type_effectiveness × STAB × accuracy.
        Status moves (no power) score 0 and are only chosen if the whole
        moveset is status moves.
        """
        def score(move: Move) -> float:
            if move.power is None:
                return 0.0
            stab = 1.5 if move.type in self.pokemon.types else 1.0
            eff = get_effectiveness(move.type, opponent.types)
            acc = (move.accuracy / 100) if move.accuracy is not None else 1.0
            return move.power * stab * eff * acc

        scored = [(score(m), m) for m in self.pokemon.moveset]
        best_score = max(s for s, _ in scored)

        if best_score == 0:
            # All status moves — pick randomly
            return random.choice(self.pokemon.moveset)

        # Break ties randomly
        best = [m for s, m in scored if s == best_score]
        return random.choice(best)

    def __repr__(self) -> str:
        return f"Trainer({self.name!r}, strategy={self.strategy!r}, pokemon={self.pokemon.name!r})"

"""Battle engine — dumb mechanical resolution. No agent logic here."""

from __future__ import annotations

import math
import random

from simulator.move import Move
from simulator.pokemon import Pokemon
from simulator.trainer import Trainer
from simulator.type_chart import get_effectiveness

# Status conditions that affect damage output or turn execution
_BURN_DAMAGE_FRACTION = 1 / 16   # fraction of max HP lost per turn
_POISON_DAMAGE_FRACTION = 1 / 8
_PARALYSIS_SKIP_CHANCE = 0.25    # probability the paralysed Pokémon can't move
_CRIT_CHANCE = 1 / 16
_CRIT_MULTIPLIER = 1.5


class BattleResult:
    """Stores the outcome of a completed battle."""

    def __init__(self, winner: Trainer, loser: Trainer, turns: int, log: list[str]) -> None:
        self.winner = winner
        self.loser = loser
        self.turns = turns
        self.log = log

    def __repr__(self) -> str:
        return f"BattleResult(winner={self.winner.name!r}, turns={self.turns})"


class Battle:
    """Runs a 1v1 Pokémon battle between two Trainers."""

    def __init__(self, trainer1: Trainer, trainer2: Trainer, verbose: bool = True) -> None:
        self.t1 = trainer1
        self.t2 = trainer2
        self.verbose = verbose
        self.log: list[str] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> BattleResult:
        """Execute the battle and return the result."""
        self._reset_battle_state()
        self._emit(f"=== {self.t1.name} vs {self.t2.name} ===")
        self._emit(f"  {self.t1.pokemon.name} vs {self.t2.pokemon.name}\n")

        turn = 0
        while not self._is_over():
            turn += 1
            self._emit(f"-- Turn {turn} --")
            self._run_turn()

        winner, loser = self._determine_winner()
        self._emit(f"\n{winner.name}'s {winner.pokemon.name} wins in {turn} turn(s)!")
        return BattleResult(winner, loser, turn, self.log)

    # ------------------------------------------------------------------
    # Turn resolution
    # ------------------------------------------------------------------

    def _run_turn(self) -> None:
        p1, p2 = self.t1.pokemon, self.t2.pokemon

        move1 = self.t1.choose_move(p2)
        move2 = self.t2.choose_move(p1)

        # Determine order by speed; ties broken randomly
        if p1.spe > p2.spe or (p1.spe == p2.spe and random.random() < 0.5):
            first, second = (self.t1, move1), (self.t2, move2)
        else:
            first, second = (self.t2, move2), (self.t1, move1)

        for trainer, move in (first, second):
            attacker = trainer.pokemon
            defender = (self.t2 if trainer is self.t1 else self.t1).pokemon

            if defender.is_fainted:
                break

            if not self._can_act(attacker):
                continue

            self._execute_move(attacker, defender, move)

        # End-of-turn status damage
        for trainer in (self.t1, self.t2):
            if not trainer.pokemon.is_fainted:
                self._apply_end_of_turn_status(trainer.pokemon)

        self._emit(
            f"  HP: {p1.name} {p1.current_hp}/{p1.hp}  |  "
            f"{p2.name} {p2.current_hp}/{p2.hp}"
        )

    def _can_act(self, pokemon: Pokemon) -> bool:
        """Return False if status prevents the Pokémon from moving this turn."""
        if pokemon.status == "paralysis" and random.random() < _PARALYSIS_SKIP_CHANCE:
            self._emit(f"  {pokemon.name} is paralyzed and can't move!")
            return False
        if pokemon.status == "freeze":
            # 20% chance to thaw each turn
            if random.random() < 0.20:
                pokemon.status = None
                self._emit(f"  {pokemon.name} thawed out!")
            else:
                self._emit(f"  {pokemon.name} is frozen solid!")
                return False
        if pokemon.status == "sleep":
            # Sleep lasts 1–3 turns (tracked via negative counter hack — not modelled here;
            # instead use a simple 33% wake-up chance per turn for simplicity)
            if random.random() < 0.33:
                pokemon.status = None
                self._emit(f"  {pokemon.name} woke up!")
            else:
                self._emit(f"  {pokemon.name} is fast asleep.")
                return False
        return True

    def _execute_move(self, attacker: Pokemon, defender: Pokemon, move: Move) -> None:
        self._emit(f"  {attacker.name} uses {move.name}!")

        # Accuracy check
        if move.accuracy is not None and random.random() > move.accuracy / 100:
            self._emit(f"  {attacker.name}'s attack missed!")
            return

        if move.category == "status":
            # Status moves — no damage; effects handled here as needed
            self._apply_status_move(attacker, defender, move)
            return

        dmg = self._calc_damage(attacker, defender, move)
        defender.current_hp = max(0, defender.current_hp - dmg)

        eff = get_effectiveness(move.type, defender.types)
        if eff == 0:
            self._emit(f"  It doesn't affect {defender.name}...")
        elif eff < 1:
            self._emit(f"  It's not very effective... ({dmg} dmg)")
        elif eff > 1:
            self._emit(f"  It's super effective! ({dmg} dmg)")
        else:
            self._emit(f"  ({dmg} dmg)")

        if defender.is_fainted:
            self._emit(f"  {defender.name} fainted!")

    # ------------------------------------------------------------------
    # Damage formula (Gen 5+)
    # ------------------------------------------------------------------

    def _calc_damage(self, attacker: Pokemon, defender: Pokemon, move: Move) -> int:
        """
        Standard damage formula:
            floor(floor(floor(2*level/5 + 2) * power * A/D / 50) + 2) * modifier
        modifier = STAB × type_effectiveness × crit × random[0.85, 1.0]
        """
        level = attacker.level

        if move.category == "physical":
            a_stat = attacker.atk
            d_stat = defender.def_
            # Burn halves physical attack
            if attacker.status == "burn":
                a_stat = math.floor(a_stat / 2)
        else:  # special
            a_stat = attacker.sp_atk
            d_stat = defender.sp_def

        base = math.floor(
            math.floor(math.floor(2 * level / 5 + 2) * move.power * a_stat / d_stat / 50) + 2
        )

        stab = 1.5 if move.type in attacker.types else 1.0
        eff = get_effectiveness(move.type, defender.types)
        crit = _CRIT_MULTIPLIER if random.random() < _CRIT_CHANCE else 1.0
        if crit > 1:
            self._emit("  A critical hit!")
        roll = random.uniform(0.85, 1.0)

        return max(1, math.floor(base * stab * eff * crit * roll))

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _apply_end_of_turn_status(self, pokemon: Pokemon) -> None:
        if pokemon.status == "burn":
            dmg = max(1, math.floor(pokemon.hp * _BURN_DAMAGE_FRACTION))
            pokemon.current_hp = max(0, pokemon.current_hp - dmg)
            self._emit(f"  {pokemon.name} is hurt by its burn! ({dmg} dmg)")
        elif pokemon.status == "poison":
            dmg = max(1, math.floor(pokemon.hp * _POISON_DAMAGE_FRACTION))
            pokemon.current_hp = max(0, pokemon.current_hp - dmg)
            self._emit(f"  {pokemon.name} is hurt by poison! ({dmg} dmg)")

    def _apply_status_move(self, attacker: Pokemon, defender: Pokemon, move: Move) -> None:
        """Placeholder — real status move effects wired in here later."""
        self._emit(f"  (Status move effect for {move.name} not yet implemented)")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _reset_battle_state(self) -> None:
        self.log = []
        for trainer in (self.t1, self.t2):
            p = trainer.pokemon
            p.current_hp = p.hp
            p.status = None

    def _is_over(self) -> bool:
        return self.t1.pokemon.is_fainted or self.t2.pokemon.is_fainted

    def _determine_winner(self) -> tuple[Trainer, Trainer]:
        if self.t2.pokemon.is_fainted:
            return self.t1, self.t2
        return self.t2, self.t1

    def _emit(self, msg: str) -> None:
        self.log.append(msg)
        if self.verbose:
            print(msg)

"""Battle engine — dumb mechanical resolution. No agent logic here."""

from __future__ import annotations

import math
import random
from typing import Union

from simulator.move import Move
from simulator.pokemon import Pokemon
from simulator.trainer import Trainer, BattleState, Action
from simulator.type_chart import get_effectiveness, weather_modifier, weather_chip_immune
from simulator.items import get_item_data
from simulator.effects import apply_secondary

_CRIT_CHANCE = 1 / 16
_CRIT_MULT = 1.5
_BURN_DAMAGE = 1 / 16
_POISON_DAMAGE = 1 / 8
_PARALYSIS_SKIP = 0.25
_FREEZE_THAW = 0.20
_SLEEP_WAKE = 0.33
_WEATHER_CHIP = 1 / 16   # sand/hail end-of-turn chip
_WEATHER_TURNS_DEFAULT = 5

# CHANGE : want to align to gen6 if we are only pulling gen6 pokemon from the API 
class BattleResult:
    """Outcome of a completed battle."""

    def __init__(
        self,
        winner: Trainer,
        loser: Trainer,
        turns: int,
        log: list[str],
    ) -> None:
        self.winner = winner
        self.loser = loser
        self.turns = turns
        self.log = log

    def __repr__(self) -> str:
        return f"BattleResult(winner={self.winner.name!r}, turns={self.turns})"


_MAX_TURNS = 200  # draw declared by HP advantage after this many turns


class Battle:
    """Runs a 6v6 Pokémon battle between two Trainers."""

    def __init__(
        self,
        trainer1: Trainer,
        trainer2: Trainer,
        weather: str | None = None,
        weather_turns: int = _WEATHER_TURNS_DEFAULT,
        verbose: bool = True,
        max_turns: int = _MAX_TURNS,
    ) -> None:
        self.t1 = trainer1
        self.t2 = trainer2
        self.weather = weather
        self.weather_turns = weather_turns if weather else 0
        self.verbose = verbose
        self.max_turns = max_turns
        self.log: list[str] = []
        self._turn = 0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> BattleResult:
        """Execute the battle and return the result."""
        self._reset_battle_state()
        self._emit(f"=== {self.t1.name} vs {self.t2.name} ===")
        self._emit(
            f"  {[p.name for p in self.t1.team]} vs {[p.name for p in self.t2.team]}\n"
        )
        if self.weather:
            self._emit(f"  Weather: {self.weather} ({self.weather_turns} turns)\n")

        while not self._is_over():
            self._turn += 1
            if self._turn > self.max_turns:
                # Time-out: winner is whoever has more remaining HP fraction
                t1_hp = sum(p.current_hp for p in self.t1.team) / max(1, sum(p.hp for p in self.t1.team))
                t2_hp = sum(p.current_hp for p in self.t2.team) / max(1, sum(p.hp for p in self.t2.team))
                winner, loser = (self.t1, self.t2) if t1_hp >= t2_hp else (self.t2, self.t1)
                self._emit(f"\nTurn limit reached! {winner.name} wins on HP advantage.")
                return BattleResult(winner, loser, self._turn, self.log)
            self._emit(f"-- Turn {self._turn} --")
            self._run_turn()

        winner, loser = (self.t1, self.t2) if not self.t1.is_defeated() else (self.t2, self.t1)
        self._emit(f"\n{winner.name} wins in {self._turn} turn(s)!")
        return BattleResult(winner, loser, self._turn, self.log)

    # ------------------------------------------------------------------
    # Turn loop
    # ------------------------------------------------------------------

    def _run_turn(self) -> None:
        state = BattleState(self.t1, self.t2, self.weather, self._turn)
        action1 = self.t1.choose_action(state)
        action2 = self.t2.choose_action(state)

        # Switches execute first (in speed order); moves execute after
        switch_pairs = []
        move_pairs = []

        for trainer, action in ((self.t1, action1), (self.t2, action2)):
            if isinstance(action, int):
                switch_pairs.append((trainer, action))
            else:
                move_pairs.append((trainer, action))

        # Execute switches (faster trainer switches first)
        switch_pairs.sort(
            key=lambda ta: self._effective_speed(ta[0]), reverse=True
        )
        for trainer, idx in switch_pairs:
            self._execute_switch(trainer, idx)

        # Execute moves: sort by priority desc, then speed desc
        move_pairs.sort(
            key=lambda ta: (ta[1].priority, self._effective_speed(ta[0])),
            reverse=True,
        )
        for trainer, move in move_pairs:
            opponent = self._opponent(trainer)
            if trainer.active.is_fainted:
                self._handle_faint_replacement(trainer)
                continue
            if opponent.active.is_fainted:
                self._handle_faint_replacement(opponent)
            if opponent.is_defeated():
                break
            if not self._can_act(trainer.active):
                continue
            self._execute_move(trainer, opponent, move)
            if self._is_over():
                break

        if not self._is_over():
            self._apply_end_of_turn()

        # Reset per-turn Protect flags for both active Pokémon
        for trainer in (self.t1, self.t2):
            p = trainer.active
            p.protect_used_last_turn = p.is_protecting
            p.is_protecting = False

        # Summary line
        p1, p2 = self.t1.active, self.t2.active
        self._emit(
            f"  HP: {p1.name} {p1.current_hp}/{p1.hp}  |  {p2.name} {p2.current_hp}/{p2.hp}"
        )

    # ------------------------------------------------------------------
    # Action resolution
    # ------------------------------------------------------------------

    def _execute_switch(self, trainer: Trainer, target_idx: int) -> None:
        if trainer.team[target_idx].is_fainted:
            self._emit(f"  {trainer.name} tried to switch to a fainted Pokémon!")
            return
        old_name = trainer.active.name
        trainer.active_index = target_idx
        trainer.choice_lock = None
        # Reset badly_poison escalation and protect state on switch-in
        incoming = trainer.active
        incoming.badly_poison_counter = 0
        incoming.is_protecting = False
        incoming.protect_used_last_turn = False
        self._emit(f"  {trainer.name} withdrew {old_name} and sent out {trainer.active.name}!")

    def _execute_move(self, trainer: Trainer, opponent: Trainer, move: Move) -> None:
        attacker = trainer.active
        defender = opponent.active
        self._emit(f"  {attacker.name} uses {move.name}!")

        # Protect check
        if defender.is_protecting and move.category != "status":
            self._emit(f"  {defender.name} is protected!")
            return

        # Accuracy check
        if move.accuracy is not None:
            acc_stage = attacker.stat_stages.get("acc", 0) - defender.stat_stages.get("eva", 0)
            acc_mult = max(0.33, min(3.0, (3 + acc_stage) / 3))
            if random.random() > (move.accuracy / 100) * acc_mult:
                self._emit(f"  {attacker.name}'s attack missed!")
                return

        # Assault Vest blocks status moves
        if move.category == "status":
            item_data = get_item_data(defender.held_item)
            if item_data.get("blocks_status_moves"):
                self._emit(f"  {defender.name}'s Assault Vest blocked the status move!")
                return
            self._apply_status_move(attacker, defender, move, trainer, opponent)
            return

        # Damage
        dmg = self._calc_damage(attacker, defender, move)
        if dmg == 0:
            self._emit(f"  It doesn't affect {defender.name}...")
            return

        # Focus Sash: survive one hit from full HP
        focus_data = get_item_data(defender.held_item)
        if (
            focus_data.get("focus_sash")
            and defender.current_hp == defender.hp
            and dmg >= defender.current_hp
        ):
            dmg = defender.current_hp - 1
            defender.held_item = None  # consumed
            self._emit(f"  {defender.name} hung on using its Focus Sash!")

        defender.current_hp = max(0, defender.current_hp - dmg)
        eff = get_effectiveness(move.type, defender.types)
        suffix = f" ({dmg} dmg)"
        if eff == 0:
            self._emit(f"  It doesn't affect {defender.name}...")
        elif eff < 1:
            self._emit(f"  It's not very effective...{suffix}")
        elif eff > 1:
            self._emit(f"  It's super effective!{suffix}")
        else:
            self._emit(f"  {suffix}")

        # Choice lock
        item_data = get_item_data(attacker.held_item)
        if item_data.get("choice_lock") and trainer.choice_lock is None:
            trainer.choice_lock = move.name

        # Life Orb recoil (applied after damage dealt)
        if attacker.held_item == "Life Orb" and not attacker.is_fainted:
            recoil = max(1, math.floor(attacker.hp / 10))
            attacker.current_hp = max(0, attacker.current_hp - recoil)
            self._emit(f"  {attacker.name} is hurt by Life Orb! (-{recoil})")

        # Rocky Helmet recoil to attacker on contact moves
        if move.contact and not attacker.is_fainted:
            helm_data = get_item_data(defender.held_item)
            frac = helm_data.get("contact_recoil_fraction", 0)
            if frac:
                recoil = max(1, math.floor(attacker.hp * frac))
                attacker.current_hp = max(0, attacker.current_hp - recoil)
                self._emit(f"  {attacker.name} was hurt by {defender.name}'s Rocky Helmet! (-{recoil})")

        # Secondary effects
        if move.secondary and not defender.is_fainted:
            apply_secondary(move, attacker, defender, self)

        if defender.is_fainted:
            self._emit(f"  {defender.name} fainted!")
            self._handle_faint_replacement(opponent)

        if attacker.is_fainted:
            self._emit(f"  {attacker.name} fainted! (recoil)")
            self._handle_faint_replacement(trainer)

        # U-turn / Volt Switch: attacker switches out after dealing damage
        if move.switch_after and not attacker.is_fainted:
            bench = trainer.alive_bench_indices()
            if bench:
                idx = random.choice(bench)
                self._execute_switch(trainer, idx)

    def _apply_status_move(
        self,
        attacker: Pokemon,
        defender: Pokemon,
        move: Move,
        trainer: Trainer,
        opponent: Trainer,
    ) -> None:
        """Resolve a status-category move via its secondary effects list."""
        if not move.secondary:
            self._emit(f"  (No effect implemented for {move.name})")
            return

        for eff in move.secondary:
            # Protect: attacker becomes protected this turn
            if eff.get("protect"):
                if attacker.protect_used_last_turn:
                    self._emit(f"  But {attacker.name} failed to protect itself!")
                else:
                    attacker.is_protecting = True
                    self._emit(f"  {attacker.name} is protecting itself!")
                return  # protect is the whole move

            # Healing
            if "heal_fraction" in eff:
                if attacker.current_hp >= attacker.hp:
                    self._emit(f"  {attacker.name}'s HP is already full!")
                else:
                    heal = max(1, math.floor(attacker.hp * eff["heal_fraction"]))
                    attacker.current_hp = min(attacker.hp, attacker.current_hp + heal)
                    self._emit(f"  {attacker.name} restored {heal} HP!")

        # All other secondaries (stat changes, status infliction) go through apply_secondary
        non_heal = [e for e in move.secondary if "heal_fraction" not in e and not e.get("protect")]
        if non_heal:
            # Temporarily replace move.secondary for the apply_secondary call
            original = move.secondary
            move.secondary = non_heal
            apply_secondary(move, attacker, defender, self)
            move.secondary = original

    # ------------------------------------------------------------------
    # Damage calculation
    # ------------------------------------------------------------------

    def _calc_damage(self, attacker: Pokemon, defender: Pokemon, move: Move) -> int:
        """Gen 5+ damage formula with stat stages, weather, and items."""
        eff = get_effectiveness(move.type, defender.types)
        if eff == 0:
            return 0

        level = attacker.level

        if move.category == "physical":
            a_stat = attacker.effective_stat("atk")
            d_stat = defender.effective_stat("def_")
            if attacker.status == "burn":
                a_stat = math.floor(a_stat / 2)
        else:
            a_stat = attacker.effective_stat("sp_atk")
            # Assault Vest boosts sp_def
            d_base = defender.effective_stat("sp_def")
            item_data = get_item_data(defender.held_item)
            d_stat = math.floor(d_base * item_data.get("sp_def_mult", 1.0))

        base = math.floor(
            math.floor(math.floor(2 * level / 5 + 2) * move.power * a_stat / d_stat / 50) + 2
        )

        stab = 1.5 if move.type in attacker.types else 1.0
        w_mod = weather_modifier(move.type, self.weather)
        crit = _CRIT_MULT if random.random() < _CRIT_CHANCE else 1.0
        if crit > 1:
            self._emit("  A critical hit!")
        roll = random.uniform(0.85, 1.0)

        # Item damage multiplier
        item_data = get_item_data(attacker.held_item)
        if move.category == "physical":
            item_mult = item_data.get("physical_damage_mult", item_data.get("damage_mult", 1.0))
        else:
            item_mult = item_data.get("special_damage_mult", item_data.get("damage_mult", 1.0))

        # Expert Belt: 1.2× on super-effective hits
        expert_belt = 1.2 if (item_data.get("expert_belt") and eff > 1) else 1.0

        # Eviolite: boost defender's def/sp_def (handled here as a defender multiplier)
        evolite_data = get_item_data(defender.held_item)
        eviolite_mult = 1.0
        if evolite_data.get("eviolite"):
            if move.category == "physical":
                eviolite_mult = evolite_data.get("def_mult", 1.0)
            else:
                eviolite_mult = evolite_data.get("sp_def_mult_eviolite", 1.0)
        # Eviolite reduces damage to defender, so divide
        eviolite_div = eviolite_mult

        return max(1, math.floor(base * stab * eff * w_mod * crit * roll * item_mult * expert_belt / eviolite_div))

    # ------------------------------------------------------------------
    # Can act / status
    # ------------------------------------------------------------------

    def _can_act(self, pokemon: Pokemon) -> bool:
        if pokemon.status == "paralysis" and random.random() < _PARALYSIS_SKIP:
            self._emit(f"  {pokemon.name} is paralyzed and can't move!")
            return False
        if pokemon.status == "freeze":
            if random.random() < _FREEZE_THAW:
                pokemon.status = None
                self._emit(f"  {pokemon.name} thawed out!")
            else:
                self._emit(f"  {pokemon.name} is frozen solid!")
                return False
        if pokemon.status == "sleep":
            if random.random() < _SLEEP_WAKE:
                pokemon.status = None
                self._emit(f"  {pokemon.name} woke up!")
            else:
                self._emit(f"  {pokemon.name} is fast asleep.")
                return False
        return True

    # ------------------------------------------------------------------
    # End-of-turn effects
    # ------------------------------------------------------------------

    def _apply_end_of_turn(self) -> None:
        # Weather countdown
        if self.weather and self.weather_turns > 0:
            self.weather_turns -= 1
            if self.weather_turns == 0:
                self._emit(f"  The {self.weather} subsided.")
                self.weather = None

        for trainer in (self.t1, self.t2):
            p = trainer.active
            if p.is_fainted:
                continue

            # Status chip damage
            if p.status == "burn":
                dmg = max(1, math.floor(p.hp * _BURN_DAMAGE))
                p.current_hp = max(0, p.current_hp - dmg)
                self._emit(f"  {p.name} is hurt by burn! (-{dmg})")
            elif p.status == "poison":
                dmg = max(1, math.floor(p.hp * _POISON_DAMAGE))
                p.current_hp = max(0, p.current_hp - dmg)
                self._emit(f"  {p.name} is hurt by poison! (-{dmg})")
            elif p.status == "badly_poison":
                p.badly_poison_counter = max(1, p.badly_poison_counter)
                dmg = max(1, math.floor(p.hp * p.badly_poison_counter / 16))
                p.current_hp = max(0, p.current_hp - dmg)
                self._emit(f"  {p.name} is badly poisoned! (-{dmg})")
                p.badly_poison_counter += 1

            # Weather chip (sand/hail)
            if self.weather in ("sand", "hail") and not weather_chip_immune(p.types, self.weather):
                dmg = max(1, math.floor(p.hp * _WEATHER_CHIP))
                p.current_hp = max(0, p.current_hp - dmg)
                self._emit(f"  {p.name} is buffeted by {self.weather}! (-{dmg})")

            # Item effects
            item_data = get_item_data(p.held_item)

            # Leftovers
            heal_frac = item_data.get("end_of_turn_heal_fraction", 0)
            if heal_frac and p.current_hp < p.hp:
                heal = max(1, math.floor(p.hp * heal_frac))
                p.current_hp = min(p.hp, p.current_hp + heal)
                self._emit(f"  {p.name} restored HP with {p.held_item}! (+{heal})")

            # Black Sludge
            if p.held_item == "Black Sludge":
                if "poison" in p.types:
                    heal = max(1, math.floor(p.hp * item_data["end_of_turn_heal_fraction_poison"]))
                    p.current_hp = min(p.hp, p.current_hp + heal)
                    self._emit(f"  {p.name} restored HP with Black Sludge! (+{heal})")
                else:
                    dmg = max(1, math.floor(p.hp * item_data["end_of_turn_damage_fraction_other"]))
                    p.current_hp = max(0, p.current_hp - dmg)
                    self._emit(f"  {p.name} was hurt by Black Sludge! (-{dmg})")

            # Lum Berry: cure status at end of turn
            if p.held_item == "Lum Berry" and p.status:
                self._emit(f"  {p.name}'s Lum Berry cured its {p.status}!")
                p.status = None
                p.badly_poison_counter = 0
                p.held_item = None  # consumed

            # Sitrus Berry: heal 25% HP once when below 50%
            sitrus_data = get_item_data(p.held_item)
            if sitrus_data.get("sitrus_berry") and p.current_hp < p.hp // 2:
                heal = max(1, math.floor(p.hp * sitrus_data["sitrus_heal_fraction"]))
                p.current_hp = min(p.hp, p.current_hp + heal)
                p.held_item = None  # consumed
                self._emit(f"  {p.name} ate its Sitrus Berry and restored {heal} HP!")

            if p.is_fainted:
                self._emit(f"  {p.name} fainted!")
                self._handle_faint_replacement(trainer)

    # ------------------------------------------------------------------
    # Faint replacement
    # ------------------------------------------------------------------

    def _handle_faint_replacement(self, trainer: Trainer) -> None:
        """Force a replacement switch when the active Pokémon faints."""
        bench = trainer.alive_bench_indices()
        if not bench:
            return  # team fully defeated — battle end detected by _is_over()

        if trainer.strategy == "random":
            idx = random.choice(bench)
        elif trainer.strategy == "stall":
            # Send in the bulkiest remaining Pokémon (highest def + sp_def sum)
            idx = max(bench, key=lambda i: trainer.team[i].def_ + trainer.team[i].sp_def)
        elif trainer.strategy in ("greedy", "minimax"):
            # Pick the bench member with the best type matchup vs opponent
            opp = self._opponent(trainer).active
            idx = max(
                bench,
                key=lambda i: max(
                    (get_effectiveness(m.type, opp.types) for m in trainer.team[i].moveset if m.power),
                    default=0.0,
                ),
            )
        else:
            idx = bench[0]

        trainer.active_index = idx
        trainer.choice_lock = None
        self._emit(f"  {trainer.name} sent out {trainer.active.name}!")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _effective_speed(self, trainer: Trainer) -> float:
        p = trainer.active
        spd = p.effective_stat("spe")
        item_data = get_item_data(p.held_item)
        spd *= item_data.get("speed_mult", 1.0)
        if p.status == "paralysis":
            spd *= 0.5
        return spd

    def _opponent(self, trainer: Trainer) -> Trainer:
        return self.t2 if trainer is self.t1 else self.t1

    def _reset_battle_state(self) -> None:
        self.log = []
        self._turn = 0
        for trainer in (self.t1, self.t2):
            trainer.active_index = 0
            trainer.choice_lock = None
            for p in trainer.team:
                p.reset_battle_state()

    def _is_over(self) -> bool:
        return self.t1.is_defeated() or self.t2.is_defeated()

    def _emit(self, msg: str) -> None:
        self.log.append(msg)
        if self.verbose:
            print(msg)

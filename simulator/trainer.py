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
        sigma: float = 0.0,
    ) -> None:
        self.name = name
        self.team = team
        self.strategy = strategy
        self.sigma = sigma
        self.active_index: int = 0
        self.choice_lock: str | None = None  # set by Choice items; cleared on switch
        self._last_hp: int = -1  # tracks HP at start of turn for stall strategy

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
        elif self.strategy == "stall":
            return self._stall_action(battle_state)
        elif self.strategy == "setup_sweep":
            return self._setup_sweep_action(battle_state)
        elif self.strategy == "noisy_greedy":
            return self._noisy_greedy_action(battle_state)
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
    # Strategy: noisy_greedy (imperfect information greedy)
    # ------------------------------------------------------------------

    def _noisy_greedy_action(self, battle_state: BattleState) -> Action:
        """Greedy with Gaussian noise applied to opponent's defensive stats.

        Uses _expected_damage (stat-based) for move scoring. At sigma=0 the
        opponent's stats are exact; at sigma>0, atk/def_/sp_atk/sp_def are each
        independently perturbed by a factor drawn from N(1, sigma). Types remain
        exact (observable). Switching logic is identical to greedy.
        """
        opp_trainer = _opponent(self, battle_state)
        opp_real = opp_trainer.active
        opp_proxy = _noisy_defender(opp_real, self.sigma)

        def _score(m: Move) -> float:
            if m.power is None:
                return _move_score(m, self.active, opp_real)
            return _expected_damage(self.active, opp_proxy, m, battle_state.weather)

        scores = [(_score(m), m) for m in self.active.moveset]
        best_score = max(s for s, _ in scores)

        bench = self.alive_bench_indices()

        if bench:
            current_best_eff = max(
                get_effectiveness(m.type, opp_real.types)
                for m in self.active.moveset
                if m.power is not None
            ) if any(m.power for m in self.active.moveset) else 0.0

            if current_best_eff < 1.0:
                for i in bench:
                    bench_mon = self.team[i]
                    bench_eff = max(
                        (get_effectiveness(m.type, opp_real.types) for m in bench_mon.moveset if m.power),
                        default=0.0,
                    )
                    if bench_eff >= 2.0:
                        return i

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

    # ------------------------------------------------------------------
    # Strategy: stall (cooperator — invests in attrition over KO pressure)
    # ------------------------------------------------------------------

    def _stall_action(self, battle_state: BattleState) -> Action:
        """
        Priority: inflict status → recover if low HP → Protect if just took a hit → best damage.
        Maps to the 'cooperator' in Axelrod terms — defers immediate damage for long-run gain.
        """
        me = self.active
        opp = _opponent(self, battle_state).active

        # Record HP now so next turn can detect damage taken (fix: update every branch)
        prev_hp = self._last_hp
        self._last_hp = me.current_hp

        moves_by_name = {m.name: m for m in me.moveset}

        # 1. Inflict badly poisoned if opponent is healthy and unstatused
        if opp.status is None:
            toxic_candidates = [
                m for m in me.moveset
                if any(e.get("inflict") in ("badly_poison", "poison") for e in m.secondary)
                and m.category == "status"
            ]
            # Prefer badly_poison (Toxic) over regular poison
            toxic_candidates.sort(
                key=lambda m: 0 if any(e.get("inflict") == "badly_poison" for e in m.secondary) else 1
            )
            if toxic_candidates:
                return toxic_candidates[0]

            # Will-O-Wisp vs physical attacker
            burn_moves = [
                m for m in me.moveset
                if any(e.get("inflict") == "burn" for e in m.secondary)
                and m.category == "status"
            ]
            if burn_moves and any(m.category == "physical" for m in opp.moveset if m.power):
                return burn_moves[0]

        # 2. Recover if HP < 45%
        if me.current_hp < me.hp * 0.45:
            recovery = [
                m for m in me.moveset
                if any("heal_fraction" in e for e in m.secondary)
            ]
            if recovery:
                return recovery[0]

        # 3. Protect if took significant damage last turn
        took_heavy_hit = (
            prev_hp > 0
            and (prev_hp - me.current_hp) > me.hp * 0.25
            and not me.protect_used_last_turn
        )
        if took_heavy_hit:
            protect = moves_by_name.get("Protect")
            if protect:
                return protect

        # 4. Fall back to best offensive/setup move (greedy scoring)
        scores = [(_move_score(m, me, opp), m) for m in me.moveset]
        best_score = max(s for s, _ in scores)
        if best_score == 0:
            return random.choice(me.moveset)
        best_moves = [m for s, m in scores if s == best_score]
        return random.choice(best_moves)

    # ------------------------------------------------------------------
    # Strategy: setup_sweep (patient — sets up, then bursts)
    # ------------------------------------------------------------------

    def _setup_sweep_action(self, battle_state: BattleState) -> Action:
        """
        Use a setup move when conditions are safe, then go all-out once boosted.
        'Patient cooperator' — different from stall in that it invests for burst damage,
        not attrition. Pays setup cost only when it won't get punished.
        """
        me = self.active
        opp = _opponent(self, battle_state).active

        # Already boosted enough — switch to full greedy
        offensive_boost = max(
            me.stat_stages.get("atk", 0),
            me.stat_stages.get("sp_atk", 0),
        )
        if offensive_boost >= 2:
            scores = [(_move_score(m, me, opp), m) for m in me.moveset if m.power]
            if scores:
                best = max(scores, key=lambda x: x[0])
                return best[1]

        # Try to set up if healthy and safe
        if me.current_hp > me.hp * 0.60:
            opp_best_dmg = max(
                (_expected_damage(opp, me, m, battle_state.weather) for m in opp.moveset if m.power),
                default=0.0,
            )
            safe = opp_best_dmg < me.current_hp * 0.40

            if safe:
                setup_moves = [
                    m for m in me.moveset
                    if m.power is None
                    and any("stat" in e and e.get("target") == "self" for e in m.secondary)
                ]
                if setup_moves:
                    # Prefer moves that boost an offensive stat
                    offensive_setup = [
                        m for m in setup_moves
                        if any(e.get("stat") in ("atk", "sp_atk") for e in m.secondary)
                    ]
                    return random.choice(offensive_setup) if offensive_setup else random.choice(setup_moves)

        # Fallback: best damage move
        damage_moves = [m for m in me.moveset if m.power]
        if not damage_moves:
            return random.choice(me.moveset)
        scores = [(_move_score(m, me, opp), m) for m in damage_moves]
        best = max(scores, key=lambda x: x[0])
        return best[1]

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


def _noisy_defender(pokemon: Pokemon, sigma: float):
    """Return a proxy for pokemon with Gaussian-noisy atk/def/sp_atk/sp_def stats.

    At sigma=0 returns the real pokemon unchanged. Otherwise each relevant stat
    is independently scaled by max(0.01, N(1, sigma)) so damage estimates are
    perturbed while types remain exact.
    """
    if sigma == 0.0:
        return pokemon

    noise = {
        stat: max(0.01, random.gauss(1.0, sigma))
        for stat in ("atk", "def_", "sp_atk", "sp_def")
    }

    class _Proxy:
        types = pokemon.types
        status = pokemon.status
        held_item = pokemon.held_item

        def effective_stat(self, stat_name: str) -> float:
            return pokemon.effective_stat(stat_name) * noise.get(stat_name, 1.0)

    return _Proxy()


def _move_score(move: Move, attacker: Pokemon, defender: Pokemon) -> float:
    """Heuristic expected damage score for greedy/minimax evaluation."""
    if move.power is None:
        # Status moves: score based on their secondary effect potential
        if any("stat" in e and e.get("target") == "self" for e in move.secondary):
            return 15.0  # setup moves are valuable
        if any(e.get("inflict") in ("badly_poison", "poison") and e.get("target") == "foe" for e in move.secondary):
            return 12.0  # Toxic / poisoning — high value if opponent is unstatused
        if any("inflict" in e for e in move.secondary):
            return 10.0  # other status (burn via Will-O-Wisp, etc.)
        if any("heal_fraction" in e for e in move.secondary):
            return 8.0   # recovery — valued when HP is low (rough heuristic)
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

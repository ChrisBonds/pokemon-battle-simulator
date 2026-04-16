"""Policy functions — one per family. All agent decision logic lives here."""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Union

from simulator.genome import FamilyType, Genome
from simulator.items import ItemUse, BAG_ITEM_DATA, apply_item
from simulator.move import Move
from simulator.type_chart import get_effectiveness, weather_modifier

if TYPE_CHECKING:
    from simulator.pokemon import Pokemon
    from simulator.trainer import BattleState, Trainer

# ---------------------------------------------------------------------------
# Type alias — avoids circular import at runtime
# ---------------------------------------------------------------------------

Action = Union[Move, int, ItemUse]

# ---------------------------------------------------------------------------
# X-item family weights — setup leans heavy on offensive boosts; stall on defense
# ---------------------------------------------------------------------------

_X_ITEM_FAMILY_WEIGHTS: dict[FamilyType, dict[str, float]] = {
    FamilyType.GREEDY: {"X Attack": 1.0, "X Sp. Atk": 1.0, "X Defense": 0.5},
    FamilyType.STALL:  {"X Attack": 0.3, "X Sp. Atk": 0.3, "X Defense": 2.0},
    FamilyType.SETUP:  {"X Attack": 2.5, "X Sp. Atk": 2.5, "X Defense": 0.3},
    FamilyType.RANDOM: {"X Attack": 1.0, "X Sp. Atk": 1.0, "X Defense": 1.0},
}

# Status moves in priority order for stall (most disabling first)
_STATUS_PRIORITY_ORDER = ["sleep", "paralysis", "badly_poison", "poison", "burn"]

# Moves that inflict each status, matched by secondary effect
_STATUS_INFLICT_KEYS = {
    "sleep":        {"sleep"},
    "paralysis":    {"paralysis"},
    "badly_poison": {"badly_poison"},
    "poison":       {"poison", "badly_poison"},
    "burn":         {"burn"},
}


# ---------------------------------------------------------------------------
# Public policy functions
# ---------------------------------------------------------------------------


def greedy_policy(trainer: "Trainer", battle_state: "BattleState", genome: Genome) -> Action:
    """Best-damage policy with probabilistic aggression and reluctant switching."""
    item_action = _maybe_use_item(trainer, genome, battle_state)
    if item_action is not None:
        return item_action

    opponent_trainer = _opponent(trainer, battle_state)
    opponent_active = opponent_trainer.active

    switch_action = _greedy_switch_check(trainer, opponent_active, genome)
    if switch_action is not None:
        return switch_action

    if random.random() < genome.aggression:
        return _best_damage_move(trainer.active, opponent_active, battle_state.weather, genome.uncertainty)
    else:
        return random.choice(trainer.active.moveset)


def stall_policy(trainer: "Trainer", battle_state: "BattleState", genome: Genome) -> Action:
    """Attrition policy: inflict status → heal → protect → switch defensively → damage."""
    item_action = _maybe_use_item(trainer, genome, battle_state)
    if item_action is not None:
        return item_action

    me = trainer.active
    opponent_active = _opponent(trainer, battle_state).active

    prev_hp = trainer._last_hp
    trainer._last_hp = me.current_hp

    # Inflict a status condition if opponent is unstatused
    if opponent_active.status is None and random.random() < genome.status_priority:
        status_move = _best_status_move(me, opponent_active)
        if status_move is not None:
            return status_move

    # Recover if HP is low
    if me.current_hp < me.hp * genome.hp_heal_threshold:
        recovery_move = _find_recovery_move(me)
        if recovery_move is not None:
            return recovery_move

    # Protect if took a heavy hit last turn
    took_heavy_hit = (
        prev_hp > 0
        and (prev_hp - me.current_hp) > me.hp * genome.protect_threshold
        and not me.protect_used_last_turn
    )
    if took_heavy_hit:
        protect_move = next((m for m in me.moveset if m.name == "Protect"), None)
        if protect_move is not None:
            return protect_move

    # Defensive switch: flee if opponent can hit hard and bench has better bulk
    switch_action = _stall_switch_check(trainer, opponent_active, genome)
    if switch_action is not None:
        return switch_action

    return _best_damage_move(me, opponent_active, battle_state.weather, uncertainty=0.0)


def setup_policy(trainer: "Trainer", battle_state: "BattleState", genome: Genome) -> Action:
    """Patient setup policy: find good matchup → set up → sweep once boosted."""
    item_action = _maybe_use_item(trainer, genome, battle_state)
    if item_action is not None:
        return item_action

    me = trainer.active
    opponent_active = _opponent(trainer, battle_state).active

    current_offensive_boost = max(
        me.stat_stages.get("atk", 0),
        me.stat_stages.get("sp_atk", 0),
    )

    # Already boosted enough — switch to pure damage
    if current_offensive_boost >= genome.boost_threshold:
        return _best_damage_move(me, opponent_active, battle_state.weather, uncertainty=0.0)

    # Proactively switch to find the best setup opportunity
    switch_action = _setup_switch_check(trainer, opponent_active, genome)
    if switch_action is not None:
        return switch_action

    # Attempt a setup move if conditions are safe
    if me.current_hp > me.hp * genome.hp_heal_threshold:
        opponent_best_damage = max(
            (_expected_damage(opponent_active, me, m, battle_state.weather) for m in opponent_active.moveset if m.power),
            default=0.0,
        )
        conditions_are_safe = opponent_best_damage < me.current_hp * (1.0 - genome.setup_willingness)
        if conditions_are_safe and random.random() < genome.setup_willingness:
            setup_move = _best_setup_move(me)
            if setup_move is not None:
                return setup_move

    return _best_damage_move(me, opponent_active, battle_state.weather, uncertainty=0.0)


def random_policy(trainer: "Trainer", battle_state: "BattleState", genome: Genome) -> Action:
    """Uniformly random action — 15% chance to switch to a random bench member."""
    bench = trainer.alive_bench_indices()
    if bench and random.random() < 0.15:
        return random.choice(bench)
    return random.choice(trainer.active.moveset)


def minimax_policy(trainer: "Trainer", battle_state: "BattleState") -> Action:
    """Depth-1 expectiminimax — enumerates all action pairs and picks the minimax-optimal action."""
    opponent_trainer = _opponent(trainer, battle_state)
    my_available_actions = _available_actions(trainer)
    opponent_available_actions = _available_actions(opponent_trainer)

    best_action: Action = my_available_actions[0]
    best_score = float("-inf")

    for my_action in my_available_actions:
        worst_case_score = float("inf")
        for opponent_action in opponent_available_actions:
            score = _simulate_pair_score(
                trainer, my_action, opponent_trainer, opponent_action, battle_state
            )
            if score < worst_case_score:
                worst_case_score = score
        if worst_case_score > best_score:
            best_score = worst_case_score
            best_action = my_action

    return best_action


# ---------------------------------------------------------------------------
# Faint replacement — each family picks its preferred bench member
# ---------------------------------------------------------------------------


def greedy_replacement(trainer: "Trainer", battle_state: "BattleState") -> int:
    """Send in the bench member with the best offensive type matchup vs current opponent."""
    opponent_active = _opponent(trainer, battle_state).active
    bench = trainer.alive_bench_indices()
    if not bench:
        return trainer.active_index
    return max(
        bench,
        key=lambda bench_index: max(
            (get_effectiveness(m.type, opponent_active.types) for m in trainer.team[bench_index].moveset if m.power),
            default=0.0,
        ),
    )


def stall_replacement(trainer: "Trainer", battle_state: "BattleState") -> int:
    """Send in the bench member with the highest combined def + sp_def."""
    bench = trainer.alive_bench_indices()
    if not bench:
        return trainer.active_index
    return max(bench, key=lambda bench_index: trainer.team[bench_index].def_ + trainer.team[bench_index].sp_def)


def setup_replacement(trainer: "Trainer", battle_state: "BattleState") -> int:
    """Send in the bench member best positioned to set up (has setup moves + good matchup)."""
    opponent_active = _opponent(trainer, battle_state).active
    bench = trainer.alive_bench_indices()
    if not bench:
        return trainer.active_index

    def _setup_score(bench_index: int) -> float:
        bench_pokemon = trainer.team[bench_index]
        has_setup_move = any(
            m.power is None and any("stat" in effect and effect.get("target") == "self" for effect in m.secondary)
            for m in bench_pokemon.moveset
        )
        offensive_effectiveness = max(
            (get_effectiveness(m.type, opponent_active.types) for m in bench_pokemon.moveset if m.power),
            default=0.0,
        )
        setup_bonus = 1.5 if has_setup_move else 1.0
        return offensive_effectiveness * setup_bonus

    return max(bench, key=_setup_score)


def random_replacement(trainer: "Trainer", battle_state: "BattleState") -> int:
    """Send in a random bench member."""
    bench = trainer.alive_bench_indices()
    if not bench:
        return trainer.active_index
    return random.choice(bench)


# ---------------------------------------------------------------------------
# Shared item helper
# ---------------------------------------------------------------------------


def _maybe_use_item(trainer: "Trainer", genome: Genome, battle_state: "BattleState") -> Action | None:
    """Return an ItemUse action if conditions and genome parameters warrant it, else None."""
    me = trainer.active
    bag = trainer.bag
    family = trainer.family
    family_weights = _X_ITEM_FAMILY_WEIGHTS.get(family, _X_ITEM_FAMILY_WEIGHTS[FamilyType.RANDOM])

    # Full Restore: cure status AND heal — highest priority healing item
    if "Full Restore" in bag and bag["Full Restore"] > 0:
        hp_is_low = me.current_hp < me.hp * genome.hp_heal_threshold
        if (me.status is not None and hp_is_low) or (me.current_hp < me.hp * (genome.hp_heal_threshold * 0.6)):
            if random.random() < genome.item_use_chance:
                return ItemUse("Full Restore")

    # Hyper Potion: heal 200 HP when below threshold
    if "Hyper Potion" in bag and bag["Hyper Potion"] > 0:
        if me.current_hp < me.hp * genome.hp_heal_threshold and me.hp - me.current_hp >= 50:
            if random.random() < genome.item_use_chance:
                return ItemUse("Hyper Potion")

    # X items: boost offensive or defensive stats
    for item_name in ("X Attack", "X Sp. Atk", "X Defense"):
        if item_name not in bag or bag[item_name] <= 0:
            continue
        item_data = BAG_ITEM_DATA[item_name]
        stat_name = item_data["stat"]
        current_stage = me.stat_stages.get(stat_name, 0)
        if current_stage >= 2:
            continue  # already boosted enough, no point using
        weight = family_weights.get(item_name, 1.0)
        if random.random() < genome.item_use_chance * weight:
            return ItemUse(item_name)

    return None


# ---------------------------------------------------------------------------
# Switch decision helpers (per family)
# ---------------------------------------------------------------------------


def _greedy_switch_check(
    trainer: "Trainer", opponent_active: "Pokemon", genome: Genome
) -> int | None:
    """Switch only when truly walled — threshold scaled down by 0.5 to encode reluctance."""
    bench = trainer.alive_bench_indices()
    if not bench:
        return None

    current_best_offensive_eff = max(
        (get_effectiveness(m.type, opponent_active.types) for m in trainer.active.moveset if m.power),
        default=0.0,
    )
    greedy_switch_floor = genome.switch_threshold * 0.5

    if current_best_offensive_eff < greedy_switch_floor:
        best_bench_index = max(
            bench,
            key=lambda bench_index: max(
                (get_effectiveness(m.type, opponent_active.types) for m in trainer.team[bench_index].moveset if m.power),
                default=0.0,
            ),
        )
        best_bench_eff = max(
            (get_effectiveness(m.type, opponent_active.types) for m in trainer.team[best_bench_index].moveset if m.power),
            default=0.0,
        )
        if best_bench_eff >= 2.0:
            return best_bench_index

    return None


def _stall_switch_check(
    trainer: "Trainer", opponent_active: "Pokemon", genome: Genome
) -> int | None:
    """Switch defensively when opponent has a strong super-effective move and bench is bulkier."""
    bench = trainer.alive_bench_indices()
    if not bench:
        return None

    me = trainer.active
    opponent_best_offensive_eff = max(
        (get_effectiveness(m.type, me.types) for m in opponent_active.moveset if m.power),
        default=0.0,
    )
    # High switch_threshold means less tolerant of being hit
    defensive_threat_floor = 2.0 - genome.switch_threshold  # e.g. threshold=0.8 → floor=1.2
    if opponent_best_offensive_eff <= defensive_threat_floor:
        return None

    # Find a bench member that is more resistant to the opponent's best type
    current_resistance = min(
        (get_effectiveness(m.type, me.types) for m in opponent_active.moveset if m.power),
        default=1.0,
    )
    for bench_index in bench:
        bench_pokemon = trainer.team[bench_index]
        bench_resistance = min(
            (get_effectiveness(m.type, bench_pokemon.types) for m in opponent_active.moveset if m.power),
            default=1.0,
        )
        if bench_resistance < current_resistance:
            return bench_index

    return None


def _setup_switch_check(
    trainer: "Trainer", opponent_active: "Pokemon", genome: Genome
) -> int | None:
    """Switch proactively to find a bench member with a good setup opportunity."""
    bench = trainer.alive_bench_indices()
    if not bench:
        return None

    for bench_index in bench:
        bench_pokemon = trainer.team[bench_index]
        bench_offensive_eff = max(
            (get_effectiveness(m.type, opponent_active.types) for m in bench_pokemon.moveset if m.power),
            default=0.0,
        )
        has_setup_moves = any(
            m.power is None and any("stat" in effect and effect.get("target") == "self" for effect in m.secondary)
            for m in bench_pokemon.moveset
        )
        if bench_offensive_eff > genome.switch_threshold and has_setup_moves:
            # Also confirm current active is not already in a better position
            current_eff = max(
                (get_effectiveness(m.type, opponent_active.types) for m in trainer.active.moveset if m.power),
                default=0.0,
            )
            if bench_offensive_eff > current_eff:
                return bench_index

    return None


# ---------------------------------------------------------------------------
# Move selection helpers
# ---------------------------------------------------------------------------


def _best_damage_move(
    attacker: "Pokemon",
    defender: "Pokemon",
    weather: str | None,
    uncertainty: float,
) -> Move:
    """Return the move with highest expected damage, with optional Gaussian noise on opponent stats."""
    if uncertainty > 0.0:
        defender_proxy = _noisy_defender(defender, uncertainty)
    else:
        defender_proxy = defender

    scored_moves = [(_move_score(m, attacker, defender_proxy, weather), m) for m in attacker.moveset]
    best_score = max(score for score, _ in scored_moves)

    if best_score == 0:
        return random.choice(attacker.moveset)

    best_moves = [m for score, m in scored_moves if score == best_score]
    return random.choice(best_moves)


def _best_status_move(attacker: "Pokemon", defender: "Pokemon") -> Move | None:
    """Return the highest-priority available status-inflicting move, or None."""
    moves_by_name = {m.name: m for m in attacker.moveset}

    for status_type in _STATUS_PRIORITY_ORDER:
        valid_inflict_values = _STATUS_INFLICT_KEYS[status_type]

        # Type immunity check
        if status_type == "burn" and "fire" in defender.types:
            continue
        if status_type in ("poison", "badly_poison") and (
            "poison" in defender.types or "steel" in defender.types
        ):
            continue
        if status_type == "paralysis" and "electric" in defender.types:
            continue
        if status_type == "freeze" and "ice" in defender.types:
            continue

        candidates = [
            m for m in attacker.moveset
            if m.category == "status"
            and any(
                effect.get("inflict") in valid_inflict_values
                for effect in m.secondary
            )
        ]
        if candidates:
            # Prefer higher accuracy
            return max(candidates, key=lambda m: m.accuracy if m.accuracy is not None else 100)

    return None


def _find_recovery_move(pokemon: "Pokemon") -> Move | None:
    """Return a recovery move if one is in the moveset."""
    recovery_candidates = [
        m for m in pokemon.moveset
        if any("heal_fraction" in effect for effect in m.secondary)
    ]
    return recovery_candidates[0] if recovery_candidates else None


def _best_setup_move(pokemon: "Pokemon") -> Move | None:
    """Return the most useful setup move based on what damage moves are available."""
    has_physical_moves = any(m.category == "physical" and m.power for m in pokemon.moveset)
    has_special_moves = any(m.category == "special" and m.power for m in pokemon.moveset)

    setup_candidates = [
        m for m in pokemon.moveset
        if m.power is None
        and any("stat" in effect and effect.get("target") == "self" for effect in m.secondary)
    ]
    if not setup_candidates:
        return None

    def _setup_move_value(setup_move: Move) -> float:
        total_value = 0.0
        for effect in setup_move.secondary:
            if effect.get("target") != "self" or "stat" not in effect:
                continue
            stat_name = effect["stat"]
            stages = effect.get("stages", 1)
            if stat_name == "atk" and has_physical_moves:
                total_value += stages * 2.0
            elif stat_name == "sp_atk" and has_special_moves:
                total_value += stages * 2.0
            elif stat_name in ("def_", "sp_def"):
                total_value += stages * 0.5
            elif stat_name == "spe":
                total_value += stages * 1.0
        return total_value

    best_value = max(_setup_move_value(m) for m in setup_candidates)
    if best_value <= 0:
        return None

    top_moves = [m for m in setup_candidates if _setup_move_value(m) == best_value]
    return random.choice(top_moves)


# ---------------------------------------------------------------------------
# Minimax helpers
# ---------------------------------------------------------------------------


def _available_actions(trainer: "Trainer") -> list[Action]:
    return list(trainer.active.moveset) + trainer.alive_bench_indices()


def _simulate_pair_score(
    me: "Trainer",
    my_action: Action,
    opponent: "Trainer",
    opponent_action: Action,
    state: "BattleState",
) -> float:
    """Estimate board score after both trainers take one action."""
    my_active = me.team[my_action] if isinstance(my_action, int) else me.active
    opponent_active = opponent.team[opponent_action] if isinstance(opponent_action, int) else opponent.active

    my_damage = 0.0
    opponent_damage = 0.0

    if isinstance(my_action, Move) and my_action.power is not None:
        my_damage = _expected_damage(my_active, opponent_active, my_action, state.weather)
    if isinstance(opponent_action, Move) and opponent_action.power is not None:
        opponent_damage = _expected_damage(opponent_active, my_active, opponent_action, state.weather)

    my_hp_after = max(0.0, my_active.current_hp - opponent_damage)
    opponent_hp_after = max(0.0, opponent_active.current_hp - my_damage)

    my_total_max = sum(p.hp for p in me.team)
    opponent_total_max = sum(p.hp for p in opponent.team)
    my_total_current = sum(p.current_hp for p in me.team)
    opponent_total_current = sum(p.current_hp for p in opponent.team)

    my_hp_fraction = (my_total_current - (my_active.current_hp - my_hp_after)) / my_total_max
    opponent_hp_fraction = (opponent_total_current - (opponent_active.current_hp - opponent_hp_after)) / opponent_total_max

    my_best_effectiveness = max(
        (get_effectiveness(m.type, opponent_active.types) for m in my_active.moveset if m.power),
        default=1.0,
    )
    opponent_best_effectiveness = max(
        (get_effectiveness(m.type, my_active.types) for m in opponent_active.moveset if m.power),
        default=1.0,
    )
    my_matchup_advantage = math.log2(my_best_effectiveness) / 2 if my_best_effectiveness > 0 else -1.0
    opponent_matchup_advantage = math.log2(opponent_best_effectiveness) / 2 if opponent_best_effectiveness > 0 else -1.0

    return (my_hp_fraction - opponent_hp_fraction) + 0.25 * (my_matchup_advantage - opponent_matchup_advantage)


# ---------------------------------------------------------------------------
# Damage math helpers (duplicated from trainer.py — single source after refactor)
# ---------------------------------------------------------------------------


def _move_score(move: Move, attacker: "Pokemon", defender: "Pokemon", weather: str | None = None) -> float:
    """Heuristic score for move selection — used by greedy and fallback paths."""
    from simulator.items import get_item_data  # local import avoids top-level circular risk

    if move.power is None:
        if any("stat" in effect and effect.get("target") == "self" for effect in move.secondary):
            return 15.0
        if any(effect.get("inflict") in ("badly_poison", "poison") and effect.get("target") == "foe" for effect in move.secondary):
            return 12.0
        if any("inflict" in effect for effect in move.secondary):
            return 10.0
        if any("heal_fraction" in effect for effect in move.secondary):
            return 8.0
        return 0.0

    stab = 1.5 if move.type in attacker.types else 1.0
    effectiveness = get_effectiveness(move.type, defender.types)
    accuracy = (move.accuracy / 100) if move.accuracy is not None else 1.0
    item_data = get_item_data(attacker.held_item)
    if move.category == "physical":
        item_multiplier = item_data.get("physical_damage_mult", item_data.get("damage_mult", 1.0))
    else:
        item_multiplier = item_data.get("special_damage_mult", item_data.get("damage_mult", 1.0))

    return move.power * stab * effectiveness * accuracy * item_multiplier


def _expected_damage(
    attacker: "Pokemon",
    defender: "Pokemon",
    move: Move,
    weather: str | None,
) -> float:
    """Deterministic expected damage (mean roll 0.925, no crit)."""
    from simulator.items import get_item_data

    if move.power is None:
        return 0.0

    if move.category == "physical":
        attack_stat = attacker.effective_stat("atk")
        defense_stat = defender.effective_stat("def_")
        if attacker.status == "burn":
            attack_stat = math.floor(attack_stat / 2)
    else:
        attack_stat = attacker.effective_stat("sp_atk")
        defense_stat = defender.effective_stat("sp_def")

    base = math.floor(
        math.floor(math.floor(2 * attacker.level / 5 + 2) * move.power * attack_stat / defense_stat / 50) + 2
    )

    stab = 1.5 if move.type in attacker.types else 1.0
    effectiveness = get_effectiveness(move.type, defender.types)
    accuracy = (move.accuracy / 100) if move.accuracy is not None else 1.0
    weather_mod = weather_modifier(move.type, weather)

    item_data = get_item_data(attacker.held_item)
    if move.category == "physical":
        item_multiplier = item_data.get("physical_damage_mult", item_data.get("damage_mult", 1.0))
    else:
        item_multiplier = item_data.get("special_damage_mult", item_data.get("damage_mult", 1.0))

    return base * stab * effectiveness * accuracy * weather_mod * item_multiplier * 0.925


def _noisy_defender(pokemon: "Pokemon", sigma: float) -> object:
    """Return a proxy for pokemon with Gaussian-noisy defensive stats."""
    noise_factors = {
        stat: max(0.01, random.gauss(1.0, sigma))
        for stat in ("atk", "def_", "sp_atk", "sp_def")
    }

    class _NoisyProxy:
        types = pokemon.types
        status = pokemon.status
        held_item = pokemon.held_item

        def effective_stat(self, stat_name: str) -> float:
            return pokemon.effective_stat(stat_name) * noise_factors.get(stat_name, 1.0)

    return _NoisyProxy()


def _opponent(trainer: "Trainer", state: "BattleState") -> "Trainer":
    return state.t2 if state.t1 is trainer else state.t1

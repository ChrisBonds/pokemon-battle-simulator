"""Build teams from the roster — archetype-based or stratified random."""

from __future__ import annotations

import copy
import json
import os
import random

from simulator.items import ITEM_DATA
from simulator.genome import FamilyType


_ARCHETYPE_ROLES = {
    "stall":     {"wall": 3, "pivot": 2, "setup_sweeper": 1},
    "offense":   {"setup_sweeper": 2, "glass_cannon": 2, "fast_attacker": 1, "tank": 1},
    "balanced":  {"wall": 2, "setup_sweeper": 2, "tank": 1, "pivot": 1},
}

STRATEGY_ARCHETYPE = {
    "stall":       "stall",
    "greedy":      "offense",
    "setup_sweep": "offense",
    "minimax":     "balanced",
    "random":      "random",
}

FAMILY_ARCHETYPE: dict[FamilyType, str] = {
    FamilyType.GREEDY: "offense",
    FamilyType.STALL:  "stall",
    FamilyType.SETUP:  "offense",
    FamilyType.RANDOM: "random",
}

_ALL_ITEMS = list(ITEM_DATA.keys())


def _sample_moveset(pokemon, rng: random.Random):
    """Return a deep copy of pokemon with 4 moves sampled from its move_pool."""
    p = copy.deepcopy(pokemon)
    pool = p.move_pool if p.move_pool else p.moveset
    p.moveset = rng.sample(pool, min(4, len(pool)))
    return p


def _assign_item(pokemon, item_pool: list[str] | None, rng: random.Random):
    """Assign a random held item from item_pool if the Pokémon has none."""
    if pokemon.held_item is None:
        candidates = item_pool if item_pool is not None else _ALL_ITEMS
        if candidates:
            pokemon.held_item = rng.choice(candidates)
    return pokemon


def build_random_team(
    pokemon_pool: list,
    item_pool: list[str] | None = None,
    team_size: int = 6,
    rng: random.Random | None = None,
) -> list:
    """Build a team using stratified type-diversity sampling.

    Greedy type-coverage selection ensures no two Pokémon share an identical
    type profile. Each Pokémon gets 4 moves sampled from its move_pool and a
    randomly assigned held item (from item_pool, or all known items if None).
    """
    if rng is None:
        rng = random.Random()

    shuffled = list(pokemon_pool)
    rng.shuffle(shuffled)

    type_counts: dict[str, int] = {}
    selected = []
    used_names: set[str] = set()

    while len(selected) < team_size and shuffled:
        # Pick the candidate that fills the most underrepresented types
        best_score = -1
        best_index = 0
        for idx, candidate in enumerate(shuffled):
            if candidate.name in used_names:
                continue
            score = sum(1 for t in candidate.types if type_counts.get(t, 0) == 0)
            if score > best_score:
                best_score = score
                best_index = idx

        chosen = shuffled.pop(best_index)
        if chosen.name in used_names:
            continue

        used_names.add(chosen.name)
        for t in chosen.types:
            type_counts[t] = type_counts.get(t, 0) + 1

        p = _sample_moveset(chosen, rng)
        _assign_item(p, item_pool, rng)
        selected.append(p)

    return selected


def build_team(
    roster: list,
    archetype: str = "random",
    rng: random.Random | None = None,
    item_pool: list[str] | None = None,
) -> list:
    """Return 6 deep-copied Pokemon from roster matching the given archetype.

    archetype: "stall" | "offense" | "balanced" | "random"
    Every Pokémon gets 4 moves sampled from its move_pool and a held item.
    """
    if rng is None:
        rng = random.Random()

    if archetype == "random" or archetype not in _ARCHETYPE_ROLES:
        weights = [getattr(p, "usage_pct", 1.0) for p in roster]
        chosen = _weighted_sample(roster, 6, weights, rng)
        result = []
        for p in chosen:
            p = _sample_moveset(p, rng)
            _assign_item(p, item_pool, rng)
            result.append(p)
        return result

    tags = _get_archetype_tags()
    roles = _ARCHETYPE_ROLES[archetype]
    selected = []
    used: set[str] = set()

    for role, count in roles.items():
        candidates = [
            p for p in roster
            if getattr(p, "archetype", tags.get(p.name)) == role and p.name not in used
        ]
        rng.shuffle(candidates)
        picked = candidates[:count]
        if len(picked) < count:
            fillers = [p for p in roster if p.name not in used and p not in picked]
            rng.shuffle(fillers)
            picked += fillers[: count - len(picked)]
        for p in picked:
            used.add(p.name)
        selected.extend(picked)

    if len(selected) < 6:
        fillers = [p for p in roster if p.name not in used]
        rng.shuffle(fillers)
        selected += fillers[: 6 - len(selected)]

    rng.shuffle(selected)
    result = []
    for p in selected[:6]:
        p = _sample_moveset(p, rng)
        _assign_item(p, item_pool, rng)
        result.append(p)
    return result


def _weighted_sample(
    population: list, k: int, weights: list[float], rng: random.Random
) -> list:
    """Sample k unique items without replacement, weighted by usage_pct."""
    k = min(k, len(population))
    chosen = []
    remaining = list(zip(weights, population))
    for _ in range(k):
        total = sum(w for w, _ in remaining)
        r = rng.random() * total
        cumul = 0.0
        for i, (w, item) in enumerate(remaining):
            cumul += w
            if cumul >= r:
                chosen.append(item)
                remaining.pop(i)
                break
    return chosen


_TAG_CACHE: dict[str, str] | None = None


def _get_archetype_tags() -> dict[str, str]:
    global _TAG_CACHE
    if _TAG_CACHE is not None:
        return _TAG_CACHE
    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "pokemon.json")
    with open(data_path) as f:
        raw = json.load(f)
    _TAG_CACHE = {entry["name"]: entry.get("archetype", "tank") for entry in raw}
    return _TAG_CACHE

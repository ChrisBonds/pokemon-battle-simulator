"""Build teams from the roster using stratified type-diversity sampling."""

from __future__ import annotations

import copy
import random

from simulator.items import ITEM_DATA

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


def build_team(
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

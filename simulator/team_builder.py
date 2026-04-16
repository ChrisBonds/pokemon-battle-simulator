"""Build archetype-appropriate teams from the roster."""

from __future__ import annotations

import copy
import json
import os
import random


_ARCHETYPE_ROLES = {
    "stall":     {"wall": 3, "pivot": 2, "setup_sweeper": 1},
    "offense":   {"setup_sweeper": 2, "glass_cannon": 2, "fast_attacker": 1, "tank": 1},
    "balanced":  {"wall": 2, "setup_sweeper": 2, "tank": 1, "pivot": 1},
}

# Strategy → preferred team archetype
STRATEGY_ARCHETYPE = {
    "stall":        "stall",
    "greedy":       "offense",
    "setup_sweep":  "offense",
    "minimax":      "balanced",
    "random":       "random",
}


def build_team(roster: list, archetype: str = "random", rng: random.Random | None = None) -> list:
    """Return 6 deep-copied Pokemon from roster matching the given archetype.

    archetype: "stall" | "offense" | "balanced" | "random"
    """
    if rng is None:
        rng = random.Random()
    
    # CHANGE : p is not descriptive enough 
    if archetype == "random" or archetype not in _ARCHETYPE_ROLES:
        # Usage-weighted sampling if usage_pct is available
        weights = [getattr(p, "usage_pct", 1.0) for p in roster]
        return [copy.deepcopy(p) for p in _weighted_sample(roster, 6, weights, rng)]

    # Load archetype tags from the JSON (cached on first call)
    tags = _get_archetype_tags()
    roles = _ARCHETYPE_ROLES[archetype]

    selected = []
    used = set()

    for role, count in roles.items():
        # Use archetype attr set by data_loader (falls back to JSON cache)
        candidates = [
            p for p in roster
            if getattr(p, "archetype", tags.get(p.name)) == role and p.name not in used
        ]
        rng.shuffle(candidates)
        picked = candidates[:count]
        # If not enough of that role, fill with anything unused
        if len(picked) < count:
            fillers = [p for p in roster if p.name not in used and p not in picked]
            rng.shuffle(fillers)
            picked += fillers[: count - len(picked)]
        for p in picked:
            used.add(p.name)
        selected.extend(picked)

    # Pad to 6 if needed
    if len(selected) < 6:
        fillers = [p for p in roster if p.name not in used]
        rng.shuffle(fillers)
        selected += fillers[: 6 - len(selected)]

    rng.shuffle(selected)
    return [copy.deepcopy(p) for p in selected[:6]]


def _weighted_sample(population: list, k: int, weights: list[float], rng: random.Random) -> list:
    """Sample k unique items without replacement, weighted by usage."""
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

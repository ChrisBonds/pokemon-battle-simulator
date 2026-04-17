"""Sanity-check data/pokemon.json after a fetch run.

Prints a summary report: counts, BST distribution, type coverage,
move pool sizes, archetype distribution, and any flagged Pokémon.

Usage:
    python scripts/validate_data.py [--data-dir data/]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict


ALL_TYPES = [
    "normal", "fire", "water", "electric", "grass", "ice",
    "fighting", "poison", "ground", "flying", "psychic", "bug",
    "rock", "ghost", "dragon", "dark", "steel", "fairy",
]

BST_BINS = [
    (300,  400, 20,  "300–399"),
    (400,  500, 60,  "400–499"),
    (500,  580, 50,  "500–579"),
    (580,  680, 30,  "580–679"),
    (680, 9999, 10,  "680+  "),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    args = parser.parse_args()

    pokemon_path = os.path.join(os.path.abspath(args.data_dir), "pokemon.json")
    with open(pokemon_path) as f:
        pool = json.load(f)

    flags: list[str] = []

    # ---- Total count ----
    print(f"{'='*55}")
    print(f"  Total Pokémon: {len(pool)}")
    print(f"{'='*55}\n")

    # ---- BST distribution ----
    print("BST Distribution:")
    print(f"  {'Range':<12} {'Count':>6}  {'Target':>6}  {'Bar'}")
    for bst_min, bst_max, target, label in BST_BINS:
        count = sum(1 for p in pool if bst_min <= p["bst"] < bst_max)
        bar = "█" * count
        delta = count - target
        delta_str = f"({delta:+d})" if delta != 0 else ""
        print(f"  {label:<12} {count:>6}  {target:>6}  {bar}  {delta_str}")
    under_300 = sum(1 for p in pool if p["bst"] < 300)
    if under_300:
        flags.append(f"{under_300} Pokémon below BST 300")
    print()

    # ---- Type coverage ----
    print("Type Coverage (Pokémon per type, dual-types count toward both):")
    type_counts: dict[str, int] = defaultdict(int)
    for p in pool:
        for t in p["types"]:
            type_counts[t] += 1

    for t in ALL_TYPES:
        count = type_counts[t]
        bar = "█" * count
        warn = " ← LOW" if count < 6 else ""
        print(f"  {t:<12} {count:>4}  {bar}{warn}")
        if count < 6:
            flags.append(f"Type '{t}' has only {count} Pokémon (target ≥ 6)")
    missing = [t for t in ALL_TYPES if type_counts[t] == 0]
    if missing:
        flags.append(f"Types with zero coverage: {missing}")
    print()

    # ---- Move pool sizes ----
    pool_sizes = [len(p.get("move_pool", p.get("moves", []))) for p in pool]
    print("Move Pool Sizes:")
    print(f"  min={min(pool_sizes)}  max={max(pool_sizes)}  mean={sum(pool_sizes)/len(pool_sizes):.1f}")
    small_pools = [p["name"] for p in pool if len(p.get("move_pool", p.get("moves", []))) < 6]
    if small_pools:
        flags.append(f"Pokémon with fewer than 6 pool moves: {small_pools}")
        print(f"  Flagged (< 6 moves): {small_pools}")
    print()

    # ---- Archetype distribution ----
    print("Archetype Distribution:")
    archetype_counts: dict[str, int] = defaultdict(int)
    for p in pool:
        archetype_counts[p.get("archetype", "unknown")] += 1
    for archetype, count in sorted(archetype_counts.items(), key=lambda x: -x[1]):
        bar = "█" * count
        print(f"  {archetype:<16} {count:>4}  {bar}")
    print()

    # ---- Flags ----
    if flags:
        print(f"{'='*55}")
        print(f"  ⚠  {len(flags)} issue(s) flagged:")
        for flag in flags:
            print(f"    • {flag}")
        print(f"{'='*55}")
    else:
        print("✓ No issues flagged.")


if __name__ == "__main__":
    main()

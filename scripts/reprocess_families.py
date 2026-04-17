"""Re-fetch Gen 6 learnsets and reassign family labels + rebuild move pools in place.

Operates on the existing pokemon.json without re-running the full census/selection
pipeline. Makes ~160 API calls (one per Pokémon) plus any uncached move fetches
needed for the new family-aware pools.

Usage:
    python scripts/reprocess_families.py [--data-dir data/] [--force] [--seed 42]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.fetch_data import (
    FAMILY_QUOTAS,
    REQUEST_DELAY,
    api_name_to_display,
    assign_family_labels,
    build_family_aware_pool,
    build_move_entry,
    build_pokemon_entry,
    ensure_move_cached,
    fetch_gen6_learnset,
    load_move_cache,
    save_move_cache,
    score_family_fitness,
)


def load_or_fetch_learnsets(
    pokemon_pool: list[dict],
    name_to_api: dict[str, str],
    learnsets_path: str,
    force: bool,
    delay: float,
) -> dict[str, list[str]]:
    """Return {api_name: [move_api_names]} for all Pokémon, fetching if needed."""
    learnsets: dict[str, list[str]] = {}

    if not force and os.path.exists(learnsets_path):
        print(f"Loading cached learnsets from {learnsets_path}")
        with open(learnsets_path) as f:
            learnsets = json.load(f)

    total = len(pokemon_pool)
    for idx, entry in enumerate(pokemon_pool):
        display_name = entry["name"]
        api_name = entry.get("api_name") or name_to_api.get(display_name)
        if api_name is None:
            print(f"  !! Could not find api_name for {display_name!r} — skipping")
            continue
        if api_name in learnsets:
            continue

        print(f"  [{idx + 1}/{total}] Fetching learnset: {display_name}")
        gen6_learnset = fetch_gen6_learnset(api_name)
        time.sleep(delay)
        if not gen6_learnset:
            print(f"    !! No Gen 6 learnset found — will use empty pool")
        learnsets[api_name] = gen6_learnset

        with open(learnsets_path, "w") as f:
            json.dump(learnsets, f, indent=2)

    return learnsets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        default=os.path.join(os.path.dirname(__file__), "..", "data"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch all learnsets even if cached",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    pokemon_path    = os.path.join(data_dir, "pokemon.json")
    census_path     = os.path.join(data_dir, "pokemon_census.json")
    learnsets_path  = os.path.join(data_dir, "pokemon_learnsets.json")
    move_cache_path = os.path.join(data_dir, "moves_cache.json")
    moves_path      = os.path.join(data_dir, "moves.json")

    rng = random.Random(args.seed)

    # ---- Load current pokemon pool ----
    with open(pokemon_path) as f:
        pokemon_pool: list[dict] = json.load(f)
    print(f"Loaded {len(pokemon_pool)} Pokémon from {pokemon_path}")

    # ---- Build display_name → api_name map from census (for entries without api_name) ----
    name_to_api: dict[str, str] = {}
    if os.path.exists(census_path):
        with open(census_path) as f:
            census = json.load(f)
        name_to_api = {entry["name"]: entry["api_name"] for entry in census}

    # ---- Load move cache ----
    move_cache = load_move_cache(move_cache_path)
    print(f"Move cache: {len(move_cache)} moves already cached")

    # ---- Fetch / load learnsets ----
    print("\nEnsuring learnsets are cached...")
    learnsets = load_or_fetch_learnsets(
        pokemon_pool, name_to_api, learnsets_path, args.force, REQUEST_DELAY
    )

    # ---- Cache any moves from learnsets that are not yet in move_cache ----
    print("\nCaching any missing moves from learnsets...")
    for api_name, gen6_learnset in learnsets.items():
        uncached = [m for m in gen6_learnset if m not in move_cache]
        if uncached:
            print(f"  {api_name}: caching {len(uncached)} moves...")
            for move_api_name in uncached:
                ensure_move_cached(move_api_name, move_cache, move_cache_path, REQUEST_DELAY)

    # ---- Build census_entry-style dicts needed by build_pokemon_entry ----
    # Reconstruct from pokemon.json + census (for api_name)
    census_by_name: dict[str, dict] = {}
    if os.path.exists(census_path):
        with open(census_path) as f:
            census = json.load(f)
        for c in census:
            census_by_name[c["name"]] = c

    # ---- Score fitness and assign family labels ----
    print("\nScoring family fitness...")
    all_fitness: list[tuple[str, dict[str, float]]] = []

    for entry in pokemon_pool:
        display_name = entry["name"]
        api_name = entry.get("api_name") or name_to_api.get(display_name)
        if api_name is None or api_name not in learnsets:
            continue
        base_stats = {
            "hp":     entry["hp"],
            "atk":    entry["atk"],
            "def":    entry["def"],
            "sp_atk": entry["sp_atk"],
            "sp_def": entry["sp_def"],
            "spe":    entry["spe"],
        }
        fitness = score_family_fitness(base_stats, learnsets[api_name])
        all_fitness.append((display_name, fitness))

    family_labels = assign_family_labels(all_fitness, FAMILY_QUOTAS)
    family_counts = {
        f: sum(1 for v in family_labels.values() if v == f)
        for f in list(FAMILY_QUOTAS) + ["random"]
    }
    print(f"Family distribution: {family_counts}")

    # ---- Rebuild move pools and rewrite pokemon entries ----
    print("\nRebuilding move pools...")
    updated_entries: list[dict] = []
    all_pool_api_names: set[str] = set()

    for entry in pokemon_pool:
        display_name = entry["name"]
        api_name = entry.get("api_name") or name_to_api.get(display_name)
        if api_name is None or api_name not in learnsets:
            print(f"  !! Skipping {display_name!r} — no learnset available")
            updated_entries.append(entry)
            continue

        gen6_learnset = learnsets[api_name]
        family = family_labels.get(display_name, "random")
        pokemon_types = entry["types"]

        pool_api_names = build_family_aware_pool(
            family, gen6_learnset, pokemon_types, move_cache, rng
        )
        if len(pool_api_names) < 6:
            print(f"  !! WARNING: only {len(pool_api_names)} moves in pool for {display_name}")

        all_pool_api_names.update(pool_api_names)

        # Build census_entry from existing data (reusing build_pokemon_entry)
        fake_census_entry = {
            "name":       display_name,
            "api_name":   api_name,
            "types":      entry["types"],
            "base_stats": {
                "hp":     entry["hp"],
                "atk":    entry["atk"],
                "def":    entry["def"],
                "sp_atk": entry["sp_atk"],
                "sp_def": entry["sp_def"],
                "spe":    entry["spe"],
            },
            "bst": entry["bst"],
        }
        updated_entry = build_pokemon_entry(
            fake_census_entry, gen6_learnset, pool_api_names, family
        )
        updated_entries.append(updated_entry)

    # ---- Write pokemon.json ----
    with open(pokemon_path, "w") as f:
        json.dump(updated_entries, f, indent=2)
    print(f"\nWrote {len(updated_entries)} Pokémon → {pokemon_path}")

    # ---- Rebuild moves.json from all pool moves ----
    print(f"\nBuilding moves.json for {len(all_pool_api_names)} pool moves...")
    move_entries: list[dict] = []
    for move_api_name in sorted(all_pool_api_names):
        raw = move_cache.get(move_api_name)
        if raw is None:
            print(f"  !! {move_api_name!r} not in cache — skipping")
            continue
        display = api_name_to_display(move_api_name)
        move_entries.append(build_move_entry(display, move_api_name, raw))

    with open(moves_path, "w") as f:
        json.dump(move_entries, f, indent=2)
    print(f"Wrote {len(move_entries)} moves → {moves_path}")

    print("\nDone. Commit data/ to repo.")


if __name__ == "__main__":
    main()

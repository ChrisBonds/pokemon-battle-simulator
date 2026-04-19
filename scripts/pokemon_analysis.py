"""
Pokemon and move analysis — runs a 50-gen baseline evolution and captures:
  - Initial vs final roster composition per family (species frequency, types, BST)
  - Final-generation pokemon performance (KOs, survival turns, stat stages)
  - Final-generation move usage (by name, type, category, power)
  - Type distribution shift from gen 0 to gen 50

Saves to data/experiments/pokemon_analysis.json.

Usage:
    python scripts/pokemon_analysis.py [--seed S]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.data_loader import load_all
from simulator.evolution import make_population, Agent
from simulator.genome import FamilyType

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
OUTPUT_PATH = os.path.join(DATA_DIR, "experiments", "pokemon_analysis.json")

FAMILIES = [FamilyType.GREEDY, FamilyType.STALL, FamilyType.SETUP, FamilyType.RANDOM]
FAMILY_NAMES = [f.value for f in FAMILIES]


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _roster_snapshot(agents: list[Agent]) -> dict:
    """Capture roster composition across all agents and broken down by family."""
    all_pokemon: list[dict] = []
    by_family: dict[str, list[dict]] = {f: [] for f in FAMILY_NAMES}

    for agent in agents:
        for pokemon in agent.roster:
            entry = {
                "name": pokemon.name,
                "types": pokemon.types,
                "bst": pokemon.bst,
                "moves": [m.name for m in pokemon.moveset],
            }
            all_pokemon.append(entry)
            by_family[agent.family.value].append(entry)

    def _summarise(pokemon_list: list[dict]) -> dict:
        freq: dict[str, int] = collections.Counter(p["name"] for p in pokemon_list)
        type_freq: dict[str, int] = collections.Counter(
            t for p in pokemon_list for t in p["types"]
        )
        bst_values = [p["bst"] for p in pokemon_list]
        return {
            "pokemon_frequency": dict(freq.most_common()),
            "type_distribution": dict(type_freq.most_common()),
            "mean_bst": sum(bst_values) / len(bst_values) if bst_values else 0.0,
            "total_slots": len(pokemon_list),
        }

    result = _summarise(all_pokemon)
    result["by_family"] = {fam: _summarise(plist) for fam, plist in by_family.items()}
    return result


def _performance_snapshot(agents: list[Agent]) -> dict:
    """Aggregate pokemon and move performance stats from the last completed generation."""
    # Pokemon-level stats
    pokemon_kos: dict[str, int] = collections.defaultdict(int)
    pokemon_turns: dict[str, int] = collections.defaultdict(int)
    pokemon_stages: dict[str, int] = collections.defaultdict(int)
    pokemon_family: dict[str, str] = {}
    pokemon_bst: dict[str, int] = {}
    pokemon_types: dict[str, list] = {}

    # Move-level stats
    move_usage: dict[str, int] = collections.defaultdict(int)

    for agent in agents:
        fam = agent.family.value
        for pokemon in agent.roster:
            name = pokemon.name
            pokemon_family[name] = fam
            pokemon_bst[name] = pokemon.bst
            pokemon_types[name] = pokemon.types
            pokemon_kos[name] += agent.pokemon_kos.get(name, 0)
            pokemon_turns[name] += agent.pokemon_turns_active.get(name, 0)
            pokemon_stages[name] += agent.pokemon_stat_stages.get(name, 0)
            for move_name, count in agent.pokemon_move_usage.get(name, {}).items():
                move_usage[move_name] += count

    # Build ranked pokemon list
    all_names = set(pokemon_kos) | set(pokemon_turns)
    pokemon_stats = sorted(
        [
            {
                "name": name,
                "family": pokemon_family.get(name, "unknown"),
                "bst": pokemon_bst.get(name, 0),
                "types": pokemon_types.get(name, []),
                "kos": pokemon_kos[name],
                "turns_active": pokemon_turns[name],
                "stat_stages": pokemon_stages[name],
            }
            for name in all_names
        ],
        key=lambda x: x["kos"],
        reverse=True,
    )

    return {
        "pokemon_stats": pokemon_stats,
        "top_10_by_kos": pokemon_stats[:10],
        "top_10_by_survival": sorted(pokemon_stats, key=lambda x: x["turns_active"], reverse=True)[:10],
    }


def _move_snapshot(agents: list[Agent], moves_db: dict) -> dict:
    """Aggregate move usage and enrich with move metadata."""
    total_usage: dict[str, int] = collections.defaultdict(int)

    for agent in agents:
        for name, usage_dict in agent.pokemon_move_usage.items():
            for move_name, count in usage_dict.items():
                total_usage[move_name] += count

    # Enrich with metadata from moves_db (keyed by move name)
    enriched: list[dict] = []
    category_totals: dict[str, int] = collections.defaultdict(int)
    type_totals: dict[str, int] = collections.defaultdict(int)

    for move_name, count in sorted(total_usage.items(), key=lambda x: x[1], reverse=True):
        move = moves_db.get(move_name)
        entry: dict = {"name": move_name, "usage": count}
        if move:
            entry["type"] = move.type
            entry["category"] = move.category
            entry["power"] = move.power
            entry["accuracy"] = move.accuracy
            category_totals[move.category] += count
            type_totals[move.type] += count
        enriched.append(entry)

    # Moveset composition from final rosters (what's in active movesets)
    moveset_usage: dict[str, int] = collections.defaultdict(int)
    moveset_category: dict[str, int] = collections.defaultdict(int)
    moveset_type: dict[str, int] = collections.defaultdict(int)

    for agent in agents:
        for pokemon in agent.roster:
            for move in pokemon.moveset:
                moveset_usage[move.name] += 1
                moveset_category[move.category] += 1
                moveset_type[move.type] += 1

    return {
        "top_moves_by_usage": enriched[:30],
        "category_usage_totals": dict(category_totals),
        "type_usage_totals": dict(sorted(type_totals.items(), key=lambda x: x[1], reverse=True)),
        "moveset_category_composition": dict(moveset_category),
        "moveset_type_composition": dict(sorted(moveset_type.items(), key=lambda x: x[1], reverse=True)),
        "top_30_moves_in_active_movesets": [
            {"name": k, "slots": v}
            for k, v in sorted(moveset_usage.items(), key=lambda x: x[1], reverse=True)[:30]
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generations", type=int, default=50)
    parser.add_argument("--agents-per-family", type=int, default=8)
    args = parser.parse_args()

    random.seed(args.seed)
    rng = random.Random(args.seed)

    print(f"Loading data from {DATA_DIR} ...")
    roster, moves_db = load_all(DATA_DIR)
    print(f"Roster: {len(roster)} Pokémon  |  Moves DB: {len(moves_db)} moves")

    family_counts = {f: args.agents_per_family for f in FAMILIES}
    pop = make_population(family_counts, roster, rng=rng)

    # Capture gen 0 roster before any evolution
    gen0_roster = _roster_snapshot(pop.agents)

    print(f"\nRunning {args.generations} generations ({args.agents_per_family}/family × 4 = {args.agents_per_family*4} agents) ...")
    t0 = time.time()
    pop.run(generations=args.generations, mutation_rate=0.05)
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f}s")

    # After run: agents have last-generation stats in their accumulators
    final_roster = _roster_snapshot(pop.agents)
    performance = _performance_snapshot(pop.agents)
    move_data = _move_snapshot(pop.agents, moves_db)

    # BST distribution comparison: bin into 50-point buckets
    def _bst_histogram(freq_dict: dict) -> dict[str, int]:
        bins: dict[str, int] = {}
        for name, count in freq_dict.items():
            # Need BST — look up from roster
            for p in roster:
                if p.name == name:
                    bucket = f"{(p.bst // 50) * 50}-{(p.bst // 50) * 50 + 49}"
                    bins[bucket] = bins.get(bucket, 0) + count
                    break
        return dict(sorted(bins.items()))

    gen0_bst_hist = _bst_histogram(gen0_roster["pokemon_frequency"])
    final_bst_hist = _bst_histogram(final_roster["pokemon_frequency"])

    # What got dropped: species in gen0 not in final, and vice versa
    gen0_species = set(gen0_roster["pokemon_frequency"])
    final_species = set(final_roster["pokemon_frequency"])
    dropped = sorted(gen0_species - final_species)
    gained = sorted(final_species - gen0_species)

    result = {
        "config": {
            "generations": args.generations,
            "agents_per_family": args.agents_per_family,
            "seed": args.seed,
        },
        "gen0_roster": gen0_roster,
        "final_roster": final_roster,
        "gen0_bst_histogram": gen0_bst_hist,
        "final_bst_histogram": final_bst_hist,
        "species_dropped": dropped,
        "species_gained_relative_prominence": gained,
        "final_gen_performance": performance,
        "final_gen_moves": move_data,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved to {OUTPUT_PATH}")

    # Print a quick summary
    print("\n=== TOP 15 POKEMON BY KOs (final generation) ===")
    print(f"  {'Name':<22} {'Family':<10} {'BST':>5} {'KOs':>5} {'Turns':>7}")
    print("  " + "-" * 55)
    for p in performance["top_10_by_kos"][:15]:
        types_str = "/".join(p["types"])
        print(f"  {p['name']:<22} {p['family']:<10} {p['bst']:>5} {p['kos']:>5} {p['turns_active']:>7}  ({types_str})")

    print("\n=== TOP 15 POKEMON BY SURVIVAL (final generation) ===")
    print(f"  {'Name':<22} {'Family':<10} {'BST':>5} {'KOs':>5} {'Turns':>7}")
    print("  " + "-" * 55)
    for p in performance["top_10_by_survival"][:15]:
        types_str = "/".join(p["types"])
        print(f"  {p['name']:<22} {p['family']:<10} {p['bst']:>5} {p['kos']:>5} {p['turns_active']:>7}  ({types_str})")

    print("\n=== TOP 20 MOVES BY USAGE (final generation) ===")
    print(f"  {'Move':<22} {'Type':<12} {'Cat':<10} {'Pwr':>5} {'Uses':>7}")
    print("  " + "-" * 60)
    for m in move_data["top_moves_by_usage"][:20]:
        pwr = str(m.get("power") or "—")
        print(f"  {m['name']:<22} {m.get('type','?'):<12} {m.get('category','?'):<10} {pwr:>5} {m['usage']:>7}")

    print("\n=== MOVE CATEGORY BREAKDOWN (actual usage) ===")
    total_cat = sum(move_data["category_usage_totals"].values())
    for cat, n in sorted(move_data["category_usage_totals"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat:<12}: {n:>6}  ({n/total_cat:.1%})")

    print("\n=== TOP TYPES BY USAGE ===")
    total_type = sum(move_data["type_usage_totals"].values())
    for typ, n in list(move_data["type_usage_totals"].items())[:10]:
        print(f"  {typ:<12}: {n:>6}  ({n/total_type:.1%})")

    print("\n=== BST HISTOGRAM (gen 0 → gen 50) ===")
    all_buckets = sorted(set(gen0_bst_hist) | set(final_bst_hist))
    print(f"  {'BST range':<12} {'gen0':>6} {'gen50':>7}")
    for b in all_buckets:
        g0 = gen0_bst_hist.get(b, 0)
        gf = final_bst_hist.get(b, 0)
        arrow = "▲" if gf > g0 + 2 else ("▼" if gf < g0 - 2 else "≈")
        print(f"  {b:<12} {g0:>6} {gf:>7}  {arrow}")

    print(f"\nSpecies no longer on any roster: {len(dropped)}")
    print(f"New species present at gen 50:   {len(gained)}")

    print("\n=== TYPE DISTRIBUTION SHIFT (gen 0 → gen 50, top 10) ===")
    g0_types = gen0_roster["type_distribution"]
    gf_types = final_roster["type_distribution"]
    all_types = sorted(set(g0_types) | set(gf_types), key=lambda t: gf_types.get(t, 0), reverse=True)
    print(f"  {'Type':<12} {'gen0':>6} {'gen50':>7}  {'delta':>7}")
    for t in all_types[:12]:
        g0 = g0_types.get(t, 0)
        gf = gf_types.get(t, 0)
        print(f"  {t:<12} {g0:>6} {gf:>7}  {gf-g0:>+7}")


if __name__ == "__main__":
    main()

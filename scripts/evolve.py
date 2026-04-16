"""
Evolutionary tournament CLI — thin wrapper around simulator.evolution.Population.

Usage:
    python scripts/evolve.py [--generations G] [--agents-per-family N]
                             [--mutation-rate R] [--team-mode random|matched|fixed]
                             [--seed S] [--output PATH]
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.data_loader import load_all
from simulator.evolution import make_population
from simulator.genome import FamilyType


def main() -> None:
    parser = argparse.ArgumentParser(description="Pokémon evolutionary tournament")
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--agents-per-family", type=int, default=8,
                        help="Number of agents per family (total = 4 × this value)")
    parser.add_argument("--mutation-rate", type=float, default=0.05)
    parser.add_argument("--team-mode", choices=["random", "matched", "fixed"], default="random")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "data", "evolution_results.json"))
    args = parser.parse_args()

    rng = random.Random(args.seed)
    random.seed(args.seed)

    data_dir = os.path.abspath(args.data_dir)
    output = os.path.abspath(args.output)

    roster, _ = load_all(data_dir)

    family_counts = {family: args.agents_per_family for family in FamilyType}
    total_agents = sum(family_counts.values())
    total_battles_per_gen = total_agents * (total_agents - 1) // 2

    print(
        f"Pop={total_agents} ({args.agents_per_family}×{len(FamilyType)} families)  "
        f"Gens={args.generations}  MutRate={args.mutation_rate}  "
        f"TeamMode={args.team_mode}  Seed={args.seed}"
    )
    print(f"Battles per generation: {total_battles_per_gen}\n")

    population = make_population(
        family_counts=family_counts,
        roster=roster,
        team_mode=args.team_mode,
        rng=rng,
    )

    snapshots = population.run(
        generations=args.generations,
        mutation_rate=args.mutation_rate,
    )

    # Print generation summaries
    for snapshot in snapshots:
        win_rates_str = "  ".join(
            f"{family}={rate:.2f}" for family, rate in snapshot.family_win_rates.items()
        )
        print(
            f"Gen {snapshot.generation:3d} | {win_rates_str} | "
            f"turns={snapshot.avg_turns:.1f}  "
            f"hp={snapshot.avg_winner_hp_fraction:.3f}  "
            f"diversity={snapshot.population_diversity:.3f}"
        )

    # Serialise snapshots — convert Genome dataclasses to dicts for JSON
    serialisable = []
    for snapshot in snapshots:
        entry = {
            "generation": snapshot.generation,
            "family_win_rates": snapshot.family_win_rates,
            "mean_genomes": snapshot.mean_genomes,
            "population_diversity": snapshot.population_diversity,
            "avg_turns": snapshot.avg_turns,
            "avg_winner_hp_fraction": snapshot.avg_winner_hp_fraction,
        }
        serialisable.append(entry)

    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w") as f:
        json.dump(serialisable, f, indent=2)
    print(f"\nWrote {len(serialisable)} generation snapshots to {output}")


if __name__ == "__main__":
    main()

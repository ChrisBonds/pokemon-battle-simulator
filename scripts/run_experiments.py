"""
Exploratory experiments — six runs saved to data/experiments/.

Usage:
    python scripts/run_experiments.py [--seed S]
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.battle import Battle
from simulator.data_loader import load_all
from simulator.evolution import (
    Agent,
    GenerationSnapshot,
    Population,
    _accumulate_pokemon_stats,
    make_population,
)
from simulator.genome import FamilyType, random_genome
from simulator.team_builder import build_team

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
OUTPUT_DIR = os.path.join(DATA_DIR, "experiments")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Population subclasses for non-standard runs
# ---------------------------------------------------------------------------


class WeatherPopulation(Population):
    """Runs all battles under a fixed weather condition."""

    def __init__(self, weather: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._weather = weather

    def run_tournament(self) -> tuple[float, float]:
        for agent in self.agents:
            agent.reset_record()
        self.pokemon_win_contributions = {}

        all_turns: list[int] = []
        all_winner_hp: list[float] = []
        agent_pairs = [
            (self.agents[i], self.agents[j])
            for i in range(len(self.agents))
            for j in range(i + 1, len(self.agents))
        ]

        for agent_a, agent_b in agent_pairs:
            trainer_a = self._build_trainer(agent_a)
            trainer_b = self._build_trainer(agent_b)
            result = Battle(trainer_a, trainer_b, weather=self._weather, verbose=False).run()

            if result.winner is trainer_a:
                agent_a.wins += 1
                agent_b.losses += 1
                winner_trainer = trainer_a
            else:
                agent_b.wins += 1
                agent_a.losses += 1
                winner_trainer = trainer_b

            _accumulate_pokemon_stats(agent_a, trainer_a.team)
            _accumulate_pokemon_stats(agent_b, trainer_b.team)
            for pokemon in winner_trainer.team:
                self.pokemon_win_contributions[pokemon.name] = (
                    self.pokemon_win_contributions.get(pokemon.name, 0) + 1
                )
            all_turns.append(result.turns)
            winner_team = result.winner.team
            all_winner_hp.append(
                sum(p.current_hp for p in winner_team)
                / max(1, sum(p.hp for p in winner_team))
            )

        avg_turns = sum(all_turns) / len(all_turns) if all_turns else 0.0
        avg_hp = sum(all_winner_hp) / len(all_winner_hp) if all_winner_hp else 0.0
        return avg_turns, avg_hp


class MinimaxPopulation(Population):
    """Population with fixed MINIMAX agents that are excluded from reproduction."""

    def evolve(self, mutation_rate: float) -> None:
        """Same as parent but MINIMAX agents never reproduce."""
        families_present = {
            agent.family for agent in self.agents if agent.family != FamilyType.MINIMAX
        }
        for family in families_present:
            family_agents = [a for a in self.agents if a.family == family]
            if len(family_agents) < 2:
                continue
            family_agents.sort(key=lambda a: a.fitness, reverse=True)
            cutoff = max(1, len(family_agents) // 2)
            top_performers = family_agents[:cutoff]
            bottom_performers = family_agents[cutoff:]
            for losing_agent in bottom_performers:
                parent = self.rng.choice(top_performers)
                from simulator.genome import mutate
                losing_agent.genome = mutate(parent.genome, mutation_rate, family)
                self._evolve_roster(losing_agent)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot_to_dict(s: GenerationSnapshot) -> dict:
    return {
        "generation": s.generation,
        "family_win_rates": s.family_win_rates,
        "population_diversity": s.population_diversity,
        "avg_turns": s.avg_turns,
        "avg_winner_hp_fraction": s.avg_winner_hp_fraction,
        "mean_roster_bst": s.mean_roster_bst,
        "roster_diversity": s.roster_diversity,
        "mean_genomes": s.mean_genomes,
    }


def _save(name: str, data: object) -> str:
    path = os.path.join(OUTPUT_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def _dominant_at_final(snapshots: list[GenerationSnapshot]) -> str:
    final = snapshots[-1].family_win_rates
    if not final:
        return "—"
    return max(final, key=lambda k: final[k])


def _diversity_at_final(snapshots: list[GenerationSnapshot]) -> float:
    return snapshots[-1].population_diversity


def _run(label: str, pop: Population, gens: int, mutation_rate: float) -> list[GenerationSnapshot]:
    t0 = time.time()
    print(f"\n--- {label} ---")
    snapshots = pop.run(generations=gens, mutation_rate=mutation_rate)
    elapsed = time.time() - t0
    final = snapshots[-1]
    wr_str = "  ".join(f"{k}={v:.2f}" for k, v in final.family_win_rates.items())
    bst_str = "  ".join(f"{k}={v:.0f}" for k, v in final.mean_roster_bst.items())
    print(f"  Final win rates: {wr_str}")
    print(f"  Final mean BST:  {bst_str}")
    print(f"  Diversity: {final.population_diversity:.3f}  elapsed={elapsed:.1f}s")
    return snapshots


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


def exp1_baseline(roster, rng) -> list[GenerationSnapshot]:
    pop = make_population(
        {FamilyType.GREEDY: 8, FamilyType.STALL: 8, FamilyType.SETUP: 8, FamilyType.RANDOM: 8},
        roster, rng=rng,
    )
    return _run("Exp 1: Baseline", pop, gens=50, mutation_rate=0.05)


def exp2_items(roster, rng) -> list[GenerationSnapshot]:
    bag = {"Hyper Potion": 2, "Full Restore": 1, "X Attack": 1}
    pop = make_population(
        {FamilyType.GREEDY: 8, FamilyType.STALL: 8, FamilyType.SETUP: 8, FamilyType.RANDOM: 8},
        roster, initial_bag=bag, rng=rng,
    )
    return _run("Exp 2: Items", pop, gens=50, mutation_rate=0.05)


def exp3_weather(roster, rng) -> dict[str, list[GenerationSnapshot]]:
    results = {}
    for weather in ("sun", "rain", "sand", "hail"):
        pop = WeatherPopulation(
            weather=weather,
            agents=make_population(
                {FamilyType.GREEDY: 8, FamilyType.STALL: 8, FamilyType.SETUP: 8, FamilyType.RANDOM: 8},
                roster, rng=rng,
            ).agents,
            roster=roster,
            rng=rng,
        )
        results[weather] = _run(f"Exp 3: Weather={weather}", pop, gens=50, mutation_rate=0.05)
    return results


def exp4_mutation_sensitivity(roster, rng) -> dict[str, list[GenerationSnapshot]]:
    results = {}
    for label, rate in [("low_0.01", 0.01), ("med_0.05", 0.05), ("high_0.20", 0.20)]:
        pop = make_population(
            {FamilyType.GREEDY: 20},
            roster, rng=rng,
        )
        results[label] = _run(f"Exp 4: GREEDY mutation={rate}", pop, gens=50, mutation_rate=rate)
    return results


def exp5_bst_drift(roster, rng) -> list[GenerationSnapshot]:
    pop = make_population(
        {FamilyType.GREEDY: 8, FamilyType.STALL: 8, FamilyType.SETUP: 8, FamilyType.RANDOM: 8},
        roster, rng=rng,
    )
    return _run("Exp 5: BST drift (baseline re-run)", pop, gens=50, mutation_rate=0.05)


def exp6_minimax(roster, rng) -> list[GenerationSnapshot]:
    base_pop = make_population(
        {FamilyType.GREEDY: 8, FamilyType.STALL: 8, FamilyType.SETUP: 8, FamilyType.RANDOM: 8},
        roster, rng=rng,
    )
    # Add 2 fixed minimax agents
    for i in range(2):
        base_pop.agents.append(
            Agent(
                trainer_name=f"minimax_{i}",
                family=FamilyType.MINIMAX,
                genome=random_genome(FamilyType.GREEDY),  # unused by minimax policy
                roster=build_team(roster, rng=rng),
                initial_bag={},
            )
        )
    mm_pop = MinimaxPopulation(
        agents=base_pop.agents,
        roster=roster,
        rng=rng,
    )
    return _run("Exp 6: Minimax presence", mm_pop, gens=50, mutation_rate=0.05)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    rng = random.Random(args.seed)

    print(f"Loading data from {DATA_DIR} ...")
    roster, _ = load_all(DATA_DIR)
    print(f"Roster size: {len(roster)} Pokémon")

    all_results: dict[str, object] = {}

    # Exp 1
    e1 = exp1_baseline(roster, random.Random(args.seed))
    all_results["exp1_baseline"] = [_snapshot_to_dict(s) for s in e1]
    _save("exp1_baseline", all_results["exp1_baseline"])

    # Exp 2
    e2 = exp2_items(roster, random.Random(args.seed))
    all_results["exp2_items"] = [_snapshot_to_dict(s) for s in e2]
    _save("exp2_items", all_results["exp2_items"])

    # Exp 3
    e3 = exp3_weather(roster, random.Random(args.seed))
    for weather, snaps in e3.items():
        key = f"exp3_weather_{weather}"
        all_results[key] = [_snapshot_to_dict(s) for s in snaps]
        _save(key, all_results[key])

    # Exp 4
    e4 = exp4_mutation_sensitivity(roster, random.Random(args.seed))
    for label, snaps in e4.items():
        key = f"exp4_{label}"
        all_results[key] = [_snapshot_to_dict(s) for s in snaps]
        _save(key, all_results[key])

    # Exp 5
    e5 = exp5_bst_drift(roster, random.Random(args.seed))
    all_results["exp5_bst_drift"] = [_snapshot_to_dict(s) for s in e5]
    _save("exp5_bst_drift", all_results["exp5_bst_drift"])

    # Exp 6
    e6 = exp6_minimax(roster, random.Random(args.seed))
    all_results["exp6_minimax"] = [_snapshot_to_dict(s) for s in e6]
    _save("exp6_minimax", all_results["exp6_minimax"])

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    print(f"{'Experiment':<30} {'Dominant @ gen50':<18} {'Diversity @ gen50':<18}")
    print("-" * 70)

    def _report(label, snaps):
        final = snaps[-1]
        dominant = max(final.family_win_rates, key=lambda k: final.family_win_rates[k]) if final.family_win_rates else "—"
        div = final.population_diversity
        print(f"{label:<30} {dominant:<18} {div:<18.3f}")

    _report("Exp1 baseline", e1)
    _report("Exp2 items", e2)
    for w, snaps in e3.items():
        _report(f"Exp3 weather={w}", snaps)
    for lbl, snaps in e4.items():
        _report(f"Exp4 greedy mutation={lbl}", snaps)
    _report("Exp5 BST drift", e5)
    _report("Exp6 minimax", e6)

    # BST drift detail
    print("\n--- BST DRIFT (Exp 5, gen 0 → gen 20) ---")
    bst_0 = e5[0].mean_roster_bst
    bst_20 = e5[-1].mean_roster_bst
    for fam in sorted(bst_0):
        delta = bst_20.get(fam, 0) - bst_0.get(fam, 0)
        print(f"  {fam:<10} gen0={bst_0.get(fam,0):.0f}  gen20={bst_20.get(fam,0):.0f}  Δ={delta:+.0f}")

    # Mutation sensitivity genome convergence
    print("\n--- GENOME CONVERGENCE (Exp 4, aggression parameter) ---")
    for lbl, snaps in e4.items():
        g0 = snaps[0].mean_genomes.get("greedy", {}).get("aggression") or 0.0
        g50 = snaps[-1].mean_genomes.get("greedy", {}).get("aggression") or 0.0
        div0 = snaps[0].population_diversity
        div50 = snaps[-1].population_diversity
        print(f"  {lbl}: aggression gen0={g0:.3f}  gen50={g50:.3f}  div: {div0:.3f}→{div50:.3f}")

    # Minimax win rate detail
    print("\n--- MINIMAX EFFECT (Exp 6) ---")
    for s in [e6[0], e6[5], e6[10], e6[25], e6[50]]:
        wr = s.family_win_rates
        print(f"  Gen {s.generation:2d}: " + "  ".join(f"{k}={v:.2f}" for k, v in wr.items()))

    # Weather winners
    print("\n--- WEATHER DOMINANT FAMILIES ---")
    for w, snaps in e3.items():
        final_wr = snaps[-1].family_win_rates
        dominant = max(final_wr, key=lambda k: final_wr[k])
        wrs = "  ".join(f"{k}={v:.2f}" for k, v in final_wr.items())
        print(f"  {w:5s}: dominant={dominant}  [{wrs}]")

    print(f"\nAll results saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

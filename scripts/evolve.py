"""
Evolutionary tournament — Axelrod-style strategy dynamics.

Each generation: round-robin fitness scoring → proportional reproduction with mutation.
Tracks strategy frequency over generations.

Inspired by Think Complexity (Downey): Evolution and Evolution of Cooperation.

Usage:
    python scripts/evolve.py [--generations G] [--pop-size N] [--battles-per-pair K]
                             [--team-mode random|matched|fixed] [--seed S]
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.battle import Battle
from simulator.data_loader import load_all
from simulator.team_builder import build_team, STRATEGY_ARCHETYPE
from simulator.trainer import Trainer

STRATEGIES = ["random", "greedy", "minimax", "stall", "setup_sweep"]


def _make_team(roster, strategy: str, team_mode: str, rng: random.Random) -> list:
    if team_mode == "matched":
        archetype = STRATEGY_ARCHETYPE.get(strategy, "random")
    elif team_mode == "fixed":
        archetype = "balanced"
    else:
        archetype = "random"
    return build_team(roster, archetype=archetype, rng=rng)


def _battle_score(t1: Trainer, t2: Trainer) -> tuple[float, float]:
    result = Battle(t1, t2, verbose=False).run()
    if result.winner is t1:
        return 1.0, 0.0
    return 0.0, 1.0


def run_generation(
    strategies: list[str],
    roster: list,
    battles_per_pair: int,
    team_mode: str,
    rng: random.Random,
) -> tuple[list[float], dict]:
    """Round-robin tournament. Returns (win_rates, stats_dict)."""
    n = len(strategies)
    scores = [0.0] * n
    games = [0] * n
    all_turns = []
    all_hp = []

    for i in range(n):
        opponents = rng.choices([j for j in range(n) if j != i], k=battles_per_pair)
        for j in opponents:
            t1 = Trainer(f"A{i}", _make_team(roster, strategies[i], team_mode, rng), strategy=strategies[i])
            t2 = Trainer(f"A{j}", _make_team(roster, strategies[j], team_mode, rng), strategy=strategies[j])
            result = Battle(t1, t2, verbose=False).run()
            s1, s2 = (1.0, 0.0) if result.winner is t1 else (0.0, 1.0)
            scores[i] += s1
            scores[j] += s2
            games[i] += 1
            games[j] += 1
            all_turns.append(result.turns)
            winner_hp = sum(p.current_hp for p in result.winner.team)
            winner_max = sum(p.hp for p in result.winner.team)
            all_hp.append(winner_hp / max(1, winner_max))

    win_rates = [scores[i] / games[i] if games[i] > 0 else 0.0 for i in range(n)]
    stats = {
        "avg_turns": round(sum(all_turns) / len(all_turns), 2) if all_turns else 0,
        "avg_winner_hp": round(sum(all_hp) / len(all_hp), 3) if all_hp else 0,
    }
    return win_rates, stats


def reproduce(
    strategies: list[str],
    win_rates: list[float],
    mutation_rate: float,
    rng: random.Random,
) -> list[str]:
    mean_fitness = sum(win_rates) / len(win_rates)
    new_strategies = []
    for strat, wr in zip(strategies, win_rates):
        if wr >= mean_fitness:
            new_strategies.append(strat)
        else:
            survivors = [s for s, w in zip(strategies, win_rates) if w >= mean_fitness]
            new_strategies.append(rng.choice(survivors) if survivors else rng.choice(STRATEGIES))
    return [rng.choice(STRATEGIES) if rng.random() < mutation_rate else s for s in new_strategies]


def strategy_frequencies(strategies: list[str]) -> dict[str, float]:
    n = len(strategies)
    freq = {s: 0 for s in STRATEGIES}
    for s in strategies:
        freq[s] += 1
    return {s: round(count / n, 4) for s, count in freq.items()}


def run_evolution(
    generations: int,
    pop_size: int,
    battles_per_pair: int,
    mutation_rate: float,
    team_mode: str,
    seed: int,
    data_dir: str,
    output: str,
) -> list[dict]:
    rng = random.Random(seed)
    random.seed(seed)

    roster, _ = load_all(data_dir)

    # Equal initial frequency of all strategies
    strategies = []
    per_strat = pop_size // len(STRATEGIES)
    for s in STRATEGIES:
        strategies.extend([s] * per_strat)
    while len(strategies) < pop_size:
        strategies.append(rng.choice(STRATEGIES))
    rng.shuffle(strategies)

    history = []
    freq0 = strategy_frequencies(strategies)
    print(f"Generation 0 — {freq0}")
    history.append({"generation": 0, "frequencies": freq0, "avg_turns": None, "avg_winner_hp": None})

    for g in range(1, generations + 1):
        win_rates, stats = run_generation(strategies, roster, battles_per_pair, team_mode, rng)
        strategies = reproduce(strategies, win_rates, mutation_rate, rng)

        freq = strategy_frequencies(strategies)
        strat_wins: dict[str, list[float]] = {s: [] for s in STRATEGIES}
        for i, s in enumerate(strategies):
            strat_wins[s].append(win_rates[i])
        fitness = {s: round(sum(v) / len(v), 3) if v else 0.0 for s, v in strat_wins.items()}

        entry = {"generation": g, "frequencies": freq, **stats, "fitness": fitness}
        history.append(entry)
        print(f"Gen {g:3d} | {freq} | turns={stats['avg_turns']} hp={stats['avg_winner_hp']} | fit={fitness}")

    with open(output, "w") as f:
        json.dump(history, f, indent=2)
    print(f"\nWrote {generations} generations to {output}")
    return history


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--generations", type=int, default=50)
    p.add_argument("--pop-size", type=int, default=40)
    p.add_argument("--battles-per-pair", type=int, default=5)
    p.add_argument("--mutation-rate", type=float, default=0.03)
    p.add_argument("--team-mode", choices=["random", "matched", "fixed"], default="random")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    p.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "data", "evolution_results.json"))
    args = p.parse_args()

    print(f"Pop={args.pop_size}  Gens={args.generations}  TeamMode={args.team_mode}  Seed={args.seed}\n")
    run_evolution(
        generations=args.generations,
        pop_size=args.pop_size,
        battles_per_pair=args.battles_per_pair,
        mutation_rate=args.mutation_rate,
        team_mode=args.team_mode,
        seed=args.seed,
        data_dir=os.path.abspath(args.data_dir),
        output=os.path.abspath(args.output),
    )


if __name__ == "__main__":
    main()

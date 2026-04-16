"""
Bulk self-play runner.

Runs battles across all family pairs with random or fixed teams and writes
structured results to data/self_play_results.json.

Usage:
    python scripts/self_play.py [--n-battles N] [--team-mode random|matched|fixed] [--seed S] [--output PATH]
    python scripts/self_play.py --uncertainty-sweep [--sigmas ...]
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.battle import Battle
from simulator.data_loader import load_all
from simulator.genome import FamilyType, Genome, random_genome
from simulator.team_builder import build_team, FAMILY_ARCHETYPE, STRATEGY_ARCHETYPE
from simulator.trainer import Trainer

FAMILIES = [FamilyType.RANDOM, FamilyType.GREEDY, FamilyType.STALL, FamilyType.SETUP]

# Default uncertainty values for --uncertainty-sweep (replaces old sigma-sweep)
DEFAULT_UNCERTAINTIES = [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]


def _get_team(roster: list, family: FamilyType, team_mode: str, rng: random.Random) -> list:
    if team_mode == "matched":
        archetype = FAMILY_ARCHETYPE.get(family, "random")
    elif team_mode == "fixed":
        archetype = "balanced"
    else:
        archetype = "random"
    return build_team(roster, archetype=archetype, rng=rng)


def _record_battle(result, family1: str, family2: str, t1_team_names: list, t2_team_names: list) -> dict:
    winner_family = family1 if result.winner.name == "T1" else family2
    loser_family = family2 if result.winner.name == "T1" else family1
    winner_hp = sum(p.current_hp for p in result.winner.team)
    winner_max = sum(p.hp for p in result.winner.team)
    return {
        "winner_family": winner_family,
        "loser_family": loser_family,
        "turns": result.turns,
        "winner_hp_frac": round(winner_hp / winner_max, 4),
        "team1_family": family1,
        "team2_family": family2,
        "team1": t1_team_names,
        "team2": t2_team_names,
    }


def run_self_play(
    n_battles: int,
    team_mode: str,
    seed: int,
    data_dir: str,
    output: str,
) -> list[dict]:
    rng = random.Random(seed)
    random.seed(seed)

    roster, _ = load_all(data_dir)
    results = []
    total = len(FAMILIES) * len(FAMILIES) * n_battles
    done = 0

    for family1 in FAMILIES:
        for family2 in FAMILIES:
            t1_wins = 0
            for _ in range(n_battles):
                team1 = _get_team(roster, family1, team_mode, rng)
                team2 = _get_team(roster, family2, team_mode, rng)
                t1_names = [p.name for p in team1]
                t2_names = [p.name for p in team2]

                t1 = Trainer("T1", team1, family1, random_genome(family1))
                t2 = Trainer("T2", team2, family2, random_genome(family2))
                result = Battle(t1, t2, verbose=False).run()

                rec = _record_battle(result, family1.value, family2.value, t1_names, t2_names)
                results.append(rec)
                if result.winner.name == "T1":
                    t1_wins += 1

                done += 1
                if done % 200 == 0:
                    print(f"  {done}/{total} battles complete...", flush=True)

            t2_wins = n_battles - t1_wins
            print(f"{family1.value:12} vs {family2.value:12} | {family1.value}: {t1_wins:3} | {family2.value}: {t2_wins:3} wins")

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w") as f:
        json.dump(results, f)
    print(f"\nWrote {len(results)} battle records to {output}")
    return results


def run_uncertainty_sweep(
    uncertainties: list[float],
    n_battles: int,
    team_mode: str,
    seed: int,
    data_dir: str,
    output: str,
) -> list[dict]:
    """Run noisy greedy vs standard greedy across uncertainty values."""
    rng = random.Random(seed)
    random.seed(seed)

    roster, _ = load_all(data_dir)
    results = []
    total = len(uncertainties) * n_battles

    print(f"Uncertainty sweep: {uncertainties}")
    print(f"  {n_battles} battles per value, noisy greedy (T1) vs greedy (T2)\n")

    done = 0
    for uncertainty_value in uncertainties:
        wins_noisy = 0
        noisy_genome = random_genome(FamilyType.GREEDY)
        clean_genome = random_genome(FamilyType.GREEDY)

        for _ in range(n_battles):
            team1 = _get_team(roster, FamilyType.GREEDY, team_mode, rng)
            team2 = _get_team(roster, FamilyType.GREEDY, team_mode, rng)
            t1_names = [p.name for p in team1]
            t2_names = [p.name for p in team2]

            noisy_genome_instance = Genome(
                **{**vars(noisy_genome), "uncertainty": uncertainty_value}
            )
            t1 = Trainer("T1", team1, FamilyType.GREEDY, noisy_genome_instance)
            t2 = Trainer("T2", team2, FamilyType.GREEDY, clean_genome)
            result = Battle(t1, t2, verbose=False).run()

            rec = _record_battle(result, "greedy_noisy", "greedy", t1_names, t2_names)
            rec["uncertainty"] = uncertainty_value
            results.append(rec)
            if result.winner.name == "T1":
                wins_noisy += 1

            done += 1
            if done % 100 == 0:
                print(f"  {done}/{total} battles complete...", flush=True)

        win_rate = wins_noisy / n_battles
        print(f"  uncertainty={uncertainty_value:.2f}  noisy_greedy wins: {wins_noisy}/{n_battles} ({win_rate:.1%})")

    existing = []
    if os.path.exists(output):
        with open(output) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass

    combined = existing + results
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w") as f:
        json.dump(combined, f)
    print(f"\nAppended {len(results)} uncertainty-sweep records → {output}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Pokémon self-play runner")
    parser.add_argument("--n-battles", type=int, default=100)
    parser.add_argument("--team-mode", choices=["random", "matched", "fixed"], default="random")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    parser.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "data", "self_play_results.json"))
    parser.add_argument("--uncertainty-sweep", action="store_true")
    parser.add_argument("--uncertainties", type=float, nargs="+", default=DEFAULT_UNCERTAINTIES)
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    output = os.path.abspath(args.output)

    if args.uncertainty_sweep:
        run_uncertainty_sweep(
            uncertainties=args.uncertainties,
            n_battles=args.n_battles,
            team_mode=args.team_mode,
            seed=args.seed,
            data_dir=data_dir,
            output=output,
        )
    else:
        print(f"Running {args.n_battles} battles × {len(FAMILIES)}²  |  team-mode={args.team_mode}  |  seed={args.seed}\n")
        run_self_play(
            n_battles=args.n_battles,
            team_mode=args.team_mode,
            seed=args.seed,
            data_dir=data_dir,
            output=output,
        )


if __name__ == "__main__":
    main()

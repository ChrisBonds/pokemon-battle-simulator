"""
Bulk self-play runner.

Runs battles across all strategy pairs with random or fixed teams and writes
structured results to data/self_play_results.json.

Usage:
    python scripts/self_play.py [--n-battles N] [--random-teams] [--seed S] [--output PATH]
"""

import argparse
import copy
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

# Default sigma values for --sigma-sweep
DEFAULT_SIGMAS = [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]


def _get_team(roster, strategy: str, team_mode: str, rng: random.Random) -> list:
    if team_mode == "matched":
        archetype = STRATEGY_ARCHETYPE.get(strategy, "random")
    elif team_mode == "fixed":
        archetype = "balanced"
    else:
        archetype = "random"
    return build_team(roster, archetype=archetype, rng=rng)


def _record_battle(result, s1: str, s2: str, t1_team_names, t2_team_names, verbose: bool) -> dict:
    winner_strat = s1 if result.winner.name == "T1" else s2
    loser_strat = s2 if result.winner.name == "T1" else s1

    winner_hp = sum(p.current_hp for p in result.winner.team)
    winner_max = sum(p.hp for p in result.winner.team)

    return {
        "winner_strategy": winner_strat,
        "loser_strategy": loser_strat,
        "turns": result.turns,
        "winner_hp_frac": round(winner_hp / winner_max, 4),
        "team1_strategy": s1,
        "team2_strategy": s2,
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
    roster_names = [p.name for p in roster]

    results = []
    total = len(STRATEGIES) * len(STRATEGIES) * n_battles
    done = 0

    for s1 in STRATEGIES:
        for s2 in STRATEGIES:
            wins = {s1: 0, s2: 0}
            for _ in range(n_battles):
                team1 = _get_team(roster, s1, team_mode, rng)
                team2 = _get_team(roster, s2, team_mode, rng)
                t1_names = [p.name for p in team1]
                t2_names = [p.name for p in team2]

                t1 = Trainer("T1", team1, strategy=s1)
                t2 = Trainer("T2", team2, strategy=s2)
                result = Battle(t1, t2, verbose=False).run()

                rec = _record_battle(result, s1, s2, t1_names, t2_names, verbose=False)
                results.append(rec)
                if rec["winner_strategy"] in wins:
                    wins[rec["winner_strategy"]] += 1

                done += 1
                if done % 200 == 0:
                    print(f"  {done}/{total} battles complete...", flush=True)

            print(f"{s1:12} vs {s2:12} | {s1}: {wins[s1]:3} | {s2}: {wins[s2]:3} wins")

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w") as f:
        json.dump(results, f)
    print(f"\nWrote {len(results)} battle records to {output}")
    return results


def run_sigma_sweep(
    sigmas: list[float],
    n_battles: int,
    team_mode: str,
    seed: int,
    data_dir: str,
    output: str,
) -> list[dict]:
    """Run noisy_greedy vs greedy at each sigma and append results to output file."""
    rng = random.Random(seed)
    random.seed(seed)

    roster, _ = load_all(data_dir)
    results = []
    total = len(sigmas) * n_battles

    print(f"Sigma sweep: {sigmas}")
    print(f"  {n_battles} battles per sigma, noisy_greedy (T1) vs greedy (T2)\n")

    done = 0
    for sigma in sigmas:
        wins_noisy = 0
        for _ in range(n_battles):
            team1 = _get_team(roster, "noisy_greedy", team_mode, rng)
            team2 = _get_team(roster, "greedy", team_mode, rng)
            t1_names = [p.name for p in team1]
            t2_names = [p.name for p in team2]

            t1 = Trainer("T1", team1, strategy="noisy_greedy", sigma=sigma)
            t2 = Trainer("T2", team2, strategy="greedy")
            result = Battle(t1, t2, verbose=False).run()

            rec = _record_battle(result, "noisy_greedy", "greedy", t1_names, t2_names, verbose=False)
            rec["sigma"] = sigma
            results.append(rec)
            if rec["winner_strategy"] == "noisy_greedy":
                wins_noisy += 1

            done += 1
            if done % 100 == 0:
                print(f"  {done}/{total} battles complete...", flush=True)

        wr = wins_noisy / n_battles
        print(f"  sigma={sigma:.2f}  noisy_greedy wins: {wins_noisy}/{n_battles} ({wr:.1%})")

    # Append to existing results file if it exists, else write fresh
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
    print(f"\nAppended {len(results)} sigma-sweep records → {output}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Pokémon self-play runner")
    p.add_argument("--n-battles", type=int, default=100)
    p.add_argument("--team-mode", choices=["random", "matched", "fixed"], default="random")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    p.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "data", "self_play_results.json"))
    p.add_argument("--sigma-sweep", action="store_true", help="Run noisy_greedy vs greedy across sigma values instead of full strategy matrix")
    p.add_argument("--sigmas", type=float, nargs="+", default=DEFAULT_SIGMAS, help="Sigma values for --sigma-sweep")
    args = p.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    output = os.path.abspath(args.output)

    if args.sigma_sweep:
        run_sigma_sweep(
            sigmas=args.sigmas,
            n_battles=args.n_battles,
            team_mode=args.team_mode,
            seed=args.seed,
            data_dir=data_dir,
            output=output,
        )
    else:
        print(f"Running {args.n_battles} battles × {len(STRATEGIES)}²  |  team-mode={args.team_mode}  |  seed={args.seed}\n")
        run_self_play(
            n_battles=args.n_battles,
            team_mode=args.team_mode,
            seed=args.seed,
            data_dir=data_dir,
            output=output,
        )


if __name__ == "__main__":
    main()

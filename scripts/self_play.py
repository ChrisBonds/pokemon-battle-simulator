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


def main() -> None:
    p = argparse.ArgumentParser(description="Pokémon self-play runner")
    p.add_argument("--n-battles", type=int, default=100)
    p.add_argument("--team-mode", choices=["random", "matched", "fixed"], default="random")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    p.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "data", "self_play_results.json"))
    args = p.parse_args()

    print(f"Running {args.n_battles} battles × {len(STRATEGIES)}²  |  team-mode={args.team_mode}  |  seed={args.seed}\n")
    run_self_play(
        n_battles=args.n_battles,
        team_mode=args.team_mode,
        seed=args.seed,
        data_dir=os.path.abspath(args.data_dir),
        output=os.path.abspath(args.output),
    )


if __name__ == "__main__":
    main()

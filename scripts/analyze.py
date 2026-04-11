"""
Analyze self-play and evolution results.

Reads data/self_play_results.json and data/evolution_results.json,
prints win rate matrix, battle length stats, HP efficiency, and
strategy frequency trajectory.

Usage:
    python scripts/analyze.py [--self-play PATH] [--evolution PATH]
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

STRATEGIES = ["random", "greedy", "minimax", "stall", "setup_sweep"]


def load_json(path: str) -> list | None:
    if not os.path.exists(path):
        print(f"  (not found: {path})")
        return None
    with open(path) as f:
        return json.load(f)


def analyze_self_play(records: list) -> None:
    print("=" * 60)
    print("SELF-PLAY ANALYSIS")
    print("=" * 60)

    # Win rate matrix: rows = s1 (team 1 strategy), cols = s2 (team 2 strategy)
    # Value = win rate for s1
    wins: dict[tuple, int] = defaultdict(int)
    totals: dict[tuple, int] = defaultdict(int)
    turn_sums: dict[tuple, float] = defaultdict(float)
    hp_sums: dict[str, float] = defaultdict(float)
    hp_counts: dict[str, int] = defaultdict(int)

    for rec in records:
        s1 = rec["team1_strategy"]
        s2 = rec["team2_strategy"]
        totals[(s1, s2)] += 1
        turn_sums[(s1, s2)] += rec["turns"]
        if rec["winner_strategy"] == s1:
            wins[(s1, s2)] += 1
        hp_sums[rec["winner_strategy"]] += rec["winner_hp_frac"]
        hp_counts[rec["winner_strategy"]] += 1

    # Win rate matrix
    col_w = 10
    header = f"{'':10}" + "".join(f"{s:>{col_w}}" for s in STRATEGIES)
    print("\nWin rate (row strategy as Team 1 vs column strategy as Team 2):\n")
    print(header)
    print("-" * len(header))
    for s1 in STRATEGIES:
        row = f"{s1:<10}"
        for s2 in STRATEGIES:
            key = (s1, s2)
            if totals[key] == 0:
                row += f"{'—':>{col_w}}"
            else:
                wr = wins[key] / totals[key]
                row += f"{wr:>{col_w}.1%}"
        print(row)

    # Average battle length
    print("\nAverage battle length (turns):\n")
    print(header)
    print("-" * len(header))
    for s1 in STRATEGIES:
        row = f"{s1:<10}"
        for s2 in STRATEGIES:
            key = (s1, s2)
            if totals[key] == 0:
                row += f"{'—':>{col_w}}"
            else:
                avg = turn_sums[key] / totals[key]
                row += f"{avg:>{col_w}.1f}"
        print(row)

    # HP efficiency: how much HP does the winner have left?
    print("\nWinner's mean remaining HP fraction (by winning strategy):\n")
    for s in STRATEGIES:
        if hp_counts[s]:
            print(f"  {s:<10}: {hp_sums[s] / hp_counts[s]:.3f}")

    # Overall win rates (marginal, regardless of matchup)
    print("\nOverall win rate (all matchups combined):\n")
    all_wins: dict[str, int] = defaultdict(int)
    all_total = len(records)
    for rec in records:
        all_wins[rec["winner_strategy"]] += 1
    for s in STRATEGIES:
        pct = all_wins[s] / all_total if all_total else 0
        print(f"  {s:<10}: {pct:.1%}  ({all_wins[s]} / {all_total})")


def analyze_evolution(history: list) -> None:
    print("\n" + "=" * 60)
    print("EVOLUTIONARY DYNAMICS")
    print("=" * 60)

    gen0 = history[0]["frequencies"]
    gen_final = history[-1]["frequencies"]
    n_gens = history[-1]["generation"]

    print(f"\nGenerations simulated: {n_gens}")
    print(f"\n{'Strategy':<12}  {'Gen 0':>8}  {'Final':>8}  {'Change':>8}")
    print("-" * 42)
    for s in STRATEGIES:
        g0 = gen0.get(s, 0)
        gf = gen_final.get(s, 0)
        delta = gf - g0
        arrow = "▲" if delta > 0.01 else ("▼" if delta < -0.01 else "≈")
        print(f"{s:<12}  {g0:>8.1%}  {gf:>8.1%}  {arrow} {delta:>+.1%}")

    # Find dominant strategy (highest final freq)
    dominant = max(STRATEGIES, key=lambda s: gen_final.get(s, 0))
    print(f"\nDominant strategy at generation {n_gens}: {dominant} ({gen_final[dominant]:.1%})")

    # Print frequency + battle stats trajectory
    print("\nFrequency + battle stats trajectory (every 10 generations):\n")
    header = f"{'Gen':>5}" + "".join(f"{s:>12}" for s in STRATEGIES) + f"{'turns':>8}{'win_hp':>8}"
    print(header)
    print("-" * len(header))
    for entry in history:
        g = entry["generation"]
        if g % 10 == 0 or g == n_gens:
            freq = entry["frequencies"]
            turns = entry.get("avg_turns") or "—"
            hp = entry.get("avg_winner_hp") or "—"
            row = f"{g:>5}" + "".join(f"{freq.get(s, 0):>12.1%}" for s in STRATEGIES)
            row += f"{str(turns):>8}{str(hp):>8}"
            print(row)


def main() -> None:
    default_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    p = argparse.ArgumentParser(description="Analyze self-play and evolution results")
    p.add_argument("--self-play", default=os.path.join(default_dir, "self_play_results.json"))
    p.add_argument("--evolution", default=os.path.join(default_dir, "evolution_results.json"))
    args = p.parse_args()

    sp = load_json(args.self_play)
    if sp:
        analyze_self_play(sp)

    ev = load_json(args.evolution)
    if ev:
        analyze_evolution(ev)


if __name__ == "__main__":
    main()

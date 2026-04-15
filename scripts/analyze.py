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


def analyze_sigma_sweep(records: list) -> None:
    """Win rate of noisy_greedy vs greedy as a function of sigma."""
    sweep = [r for r in records if "sigma" in r]
    if not sweep:
        return

    print("\n" + "=" * 60)
    print("SIGMA SWEEP: noisy_greedy vs greedy")
    print("=" * 60)

    wins: dict[float, int] = defaultdict(int)
    totals: dict[float, int] = defaultdict(int)

    for rec in sweep:
        sigma = rec["sigma"]
        totals[sigma] += 1
        if rec["winner_strategy"] == "noisy_greedy":
            wins[sigma] += 1

    print(f"\n{'sigma':>8}  {'noisy_greedy wins':>18}  {'win rate':>10}")
    print("-" * 42)
    for sigma in sorted(totals):
        n = totals[sigma]
        w = wins[sigma]
        print(f"{sigma:>8.2f}  {w:>9} / {n:<8}  {w/n:>9.1%}")


def analyze_legendary(records: list, pokemon_path: str) -> None:
    """Win rate for legendary-heavy teams (>=2 legendaries) vs non-legendary teams."""
    if not records:
        return

    # Load is_legendary lookup; no-op if data hasn't been enriched yet
    if not os.path.exists(pokemon_path):
        return
    with open(pokemon_path) as f:
        poke_list = json.load(f)

    legendary_set = {p["name"] for p in poke_list if p.get("is_legendary", False)}
    if not legendary_set:
        print("  (no is_legendary data found in pokemon.json — re-run fetch_data.py)")
        return

    print("\n" + "=" * 60)
    print("LEGENDARY TEAM ANALYSIS (>=2 legendaries = 'heavy')")
    print("=" * 60)

    def is_heavy(team_names: list) -> bool:
        return sum(1 for n in team_names if n in legendary_set) >= 2

    results: dict[str, dict[str, int]] = {
        "heavy_vs_light": {"wins": 0, "total": 0},
        "heavy_vs_heavy": {"wins": 0, "total": 0},
        "light_vs_light": {"wins": 0, "total": 0},
    }

    for rec in records:
        t1 = rec.get("team1", [])
        t2 = rec.get("team2", [])
        if not t1 or not t2:
            continue
        h1 = is_heavy(t1)
        h2 = is_heavy(t2)
        t1_won = rec["winner_strategy"] == rec["team1_strategy"]

        if h1 and not h2:
            results["heavy_vs_light"]["total"] += 1
            if t1_won:
                results["heavy_vs_light"]["wins"] += 1
        elif h1 and h2:
            results["heavy_vs_heavy"]["total"] += 1
            if t1_won:
                results["heavy_vs_heavy"]["wins"] += 1
        elif not h1 and not h2:
            results["light_vs_light"]["total"] += 1
            if t1_won:
                results["light_vs_light"]["wins"] += 1

    print(f"\n{'matchup':<20}  {'T1 wins':>10}  {'win rate':>10}")
    print("-" * 44)
    for label, d in results.items():
        if d["total"] == 0:
            print(f"{label:<20}  {'—':>10}  {'—':>10}")
        else:
            print(f"{label:<20}  {d['wins']:>5} / {d['total']:<4}  {d['wins']/d['total']:>9.1%}")


def main() -> None:
    default_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    p = argparse.ArgumentParser(description="Analyze self-play and evolution results")
    p.add_argument("--self-play", default=os.path.join(default_dir, "self_play_results.json"))
    p.add_argument("--evolution", default=os.path.join(default_dir, "evolution_results.json"))
    p.add_argument("--pokemon", default=os.path.join(default_dir, "pokemon.json"))
    args = p.parse_args()

    sp = load_json(args.self_play)
    if sp:
        analyze_self_play(sp)
        analyze_sigma_sweep(sp)
        analyze_legendary(sp, args.pokemon)

    ev = load_json(args.evolution)
    if ev:
        analyze_evolution(ev)


if __name__ == "__main__":
    main()

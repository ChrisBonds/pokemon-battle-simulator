"""
Generates notebooks/demo.ipynb from cell definitions below.
Run this script any time you want to regenerate the notebook from scratch.

Usage:
    python scripts/generate_notebook.py
"""

import json
import os
import sys

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "notebooks", "demo.ipynb"))

cells = []


def md(source: str) -> None:
    cells.append({"cell_type": "markdown", "metadata": {}, "source": source.strip()})


def code(source: str) -> None:
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.strip(),
    })


# ===========================================================================
# TITLE
# ===========================================================================

md("""\
# Pokémon Battle ABM — Evolution of Strategy

**ENGG\\*3130 Modelling Complex Systems · University of Guelph · April 2026**

This notebook demonstrates our agent-based model of Pokémon battles as a study in the
*evolution of cooperation* (Downey, *Think Complexity* Ch. 12). Instead of a Prisoner's Dilemma
payoff matrix, fitness is determined by high-fidelity Gen 6 battle mechanics: type
effectiveness, stat stages, status conditions, held items, and weather.

Four behavioural families compete in a round-robin tournament each generation.
The bottom half of each family is replaced by mutated copies of the top half.
Genomes (continuous behavioural parameters) and rosters (the 6 Pokémon each agent fields)
both evolve independently.

| Family | Strategy | PD analogue |
|--------|----------|-------------|
| `greedy` | Maximise expected damage each turn | Always Defect |
| `stall`  | Outlast via recovery and status | Always Cooperate (passive) |
| `setup`  | Accumulate stat boosts, then burst | Tit-for-Tat (patient) |
| `random` | Choose any legal action uniformly | Random |

> All multi-generation simulations were pre-computed and are loaded from disk.
> Only the single-battle demo (§1) and the interactive mini-experiment (§8) run live.
""")

# ===========================================================================
# SECTION 0 — SETUP
# ===========================================================================

md("## 0 · Setup")

code("""\
%matplotlib inline
%config InlineBackend.figure_format = "svg"

import copy, json, os, random, sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns

# ── path wiring ──────────────────────────────────────────────────────────────
NB_DIR = Path().resolve()
PROJECT_ROOT = NB_DIR.parent if NB_DIR.name == "notebooks" else NB_DIR
DATA_DIR  = PROJECT_ROOT / "data"
EXP_DIR   = DATA_DIR / "experiments"
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.battle import Battle
from simulator.data_loader import load_all
from simulator.evolution import make_population
from simulator.genome import FamilyType, random_genome
from simulator.team_builder import build_team
from simulator.trainer import Trainer

roster, moves_db = load_all(str(DATA_DIR))
print(f"Loaded {len(roster)} Pokémon and {len(moves_db)} moves.")

# ── shared style ─────────────────────────────────────────────────────────────
FAMILIES = ["greedy", "stall", "setup", "random"]
PALETTE  = {"greedy": "#e15759", "stall": "#4e79a7", "setup": "#59a14f",
            "random": "#b07aa1", "minimax": "#2f2f2f"}
sns.set_theme(style="whitegrid", font_scale=1.0)

def load_exp(name: str) -> list[dict]:
    with open(EXP_DIR / f"{name}.json") as f:
        return json.load(f)
""")

# ===========================================================================
# SECTION 1 — LIVE BATTLE DEMO
# ===========================================================================

md("""\
## 1 · A Single Battle: Watching the System Work

Before any statistics, we watch one battle play out between a **greedy** trainer
(always uses the highest expected-damage move) and a **stall** trainer (tries to
outlast via recovery and status moves). The HP timeline shows the contrasting
strategies: greedy tries to win quickly; stall tries to drag it out.
""")

code("""\
# ── build trainers ────────────────────────────────────────────────────────────
rng = random.Random(42)
t1 = Trainer("Gary",  build_team(roster, rng=rng),
             family=FamilyType.GREEDY, genome=random_genome(FamilyType.GREEDY))
t2 = Trainer("Brock", build_team(roster, rng=rng),
             family=FamilyType.STALL,  genome=random_genome(FamilyType.STALL))

result = Battle(t1, t2, verbose=False).run()
print(f"Winner : {result.winner.name}   ({result.turns} turns)")
hp_left = sum(p.current_hp for p in result.winner.team)
hp_max  = sum(p.hp         for p in result.winner.team)
print(f"Winner HP remaining: {hp_left}/{hp_max}  ({hp_left/hp_max:.1%})")
print()
print("── Battle log (first 40 lines) ─────────────────────────────────────")
for line in result.log[:40]:
    print(" ", line)
""")

code("""\
# ── HP timeline ──────────────────────────────────────────────────────────────
class TrackedBattle(Battle):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.hp_trace: list[tuple[float, float]] = []

    def _run_turn(self) -> None:
        super()._run_turn()
        f1 = sum(p.current_hp for p in self.t1.team) / max(1, sum(p.hp for p in self.t1.team))
        f2 = sum(p.current_hp for p in self.t2.team) / max(1, sum(p.hp for p in self.t2.team))
        self.hp_trace.append((f1, f2))

rng2 = random.Random(42)
tb = TrackedBattle(
    Trainer("Gary",  build_team(roster, rng=rng2),
            family=FamilyType.GREEDY, genome=random_genome(FamilyType.GREEDY)),
    Trainer("Brock", build_team(roster, rng=rng2),
            family=FamilyType.STALL,  genome=random_genome(FamilyType.STALL)),
    verbose=False,
)
tb.run()

turns = list(range(1, len(tb.hp_trace) + 1))
fig, ax = plt.subplots(figsize=(8, 3.5))
ax.plot(turns, [x[0] for x in tb.hp_trace], color=PALETTE["greedy"], lw=2, label="Gary (greedy)")
ax.plot(turns, [x[1] for x in tb.hp_trace], color=PALETTE["stall"],  lw=2, label="Brock (stall)")
ax.set_xlabel("Turn"); ax.set_ylabel("Team HP fraction")
ax.set_title("HP Timeline — Greedy vs Stall (seed 42)")
ax.set_ylim(0, 1.05); ax.legend(frameon=False)
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.show()
""")

# ===========================================================================
# SECTION 2 — STATIC STRATEGY LANDSCAPE
# ===========================================================================

md("""\
## 2 · Static Strategy Landscape

Before anything evolves, we establish the baseline competitive landscape from
**1 600 pre-computed battles** (100 per family pair). This is our "payoff matrix" —
equivalent to the cooperation/defection table in the Prisoner's Dilemma.
""")

code("""\
with open(DATA_DIR / "self_play_results.json") as f:
    sp = json.load(f)
print(f"Loaded {len(sp)} battle records.")
""")

code("""\
# ── win-rate heatmap ─────────────────────────────────────────────────────────
wins   = defaultdict(int)
totals = defaultdict(int)
turn_sums = defaultdict(float)
hp_by_winner = defaultdict(list)

for rec in sp:
    f1, f2 = rec["team1_family"], rec["team2_family"]
    totals[(f1, f2)] += 1
    turn_sums[(f1, f2)] += rec["turns"]
    if rec["winner_family"] == f1:
        wins[(f1, f2)] += 1
    hp_by_winner[rec["winner_family"]].append(rec["winner_hp_frac"])

wr_matrix = pd.DataFrame(
    {f2: {f1: wins[(f1,f2)] / totals[(f1,f2)] if totals[(f1,f2)] else float("nan")
          for f1 in FAMILIES} for f2 in FAMILIES}
)[FAMILIES].loc[FAMILIES]

fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

sns.heatmap(wr_matrix.astype(float), annot=True, fmt=".0%",
            cmap="RdYlGn", vmin=0, vmax=1, linewidths=0.5, ax=axes[0])
axes[0].set_title("Win Rate  (row = Team 1, col = Team 2)", fontsize=11)
axes[0].set_xlabel("Team 2 Family"); axes[0].set_ylabel("Team 1 Family")

turn_matrix = pd.DataFrame(
    {f2: {f1: turn_sums[(f1,f2)] / totals[(f1,f2)] if totals[(f1,f2)] else float("nan")
          for f1 in FAMILIES} for f2 in FAMILIES}
)[FAMILIES].loc[FAMILIES]

sns.heatmap(turn_matrix.astype(float), annot=True, fmt=".0f",
            cmap="YlOrRd", linewidths=0.5, ax=axes[1])
axes[1].set_title("Average Battle Length (turns)", fontsize=11)
axes[1].set_xlabel("Team 2 Family"); axes[1].set_ylabel("")

plt.suptitle("Static Strategy Landscape — 1 600 battles, no evolution", y=1.01, fontsize=12)
plt.tight_layout(); plt.show()
print("Green = row strategy dominates.  Stall × Stall produces the longest battles by far.")
""")

code("""\
# ── winner HP efficiency ─────────────────────────────────────────────────────
means  = {f: np.mean(hp_by_winner[f])  for f in FAMILIES if hp_by_winner[f]}
errors = {f: np.std(hp_by_winner[f])   for f in FAMILIES if hp_by_winner[f]}

fig, ax = plt.subplots(figsize=(6, 3.5))
x = np.arange(len(FAMILIES))
bars = ax.bar(x, [means[f] for f in FAMILIES], yerr=[errors[f] for f in FAMILIES],
              color=[PALETTE[f] for f in FAMILIES], capsize=5, edgecolor="white")
ax.set_xticks(x); ax.set_xticklabels(FAMILIES)
ax.set_ylabel("Mean remaining HP fraction")
ax.set_title("HP Efficiency When Winning  (mean ± 1 SD)")
ax.set_ylim(0, 0.65)
ax.spines[["top","right"]].set_visible(False)
plt.tight_layout(); plt.show()
print("Greedy wins cheaply (high HP left); stall wins expensively (attrition grinds both sides down).")
""")

# ===========================================================================
# SECTION 3 — EVOLUTIONARY RACE
# ===========================================================================

md("""\
## 3 · The Evolutionary Race: 50 Generations

We run a round-robin tournament each generation (8 agents per family, 32 total,
496 battles per generation). The bottom half of each family is replaced by mutated
copies of the top half. Rosters also evolve: the Pokémon with the worst family-specific
fitness signal gets cut and replaced each generation.

> **Pre-computed:** `data/experiments/exp1_baseline.json` — 8 agents/family, 50 gens.
""")

code("""\
e1 = load_exp("exp1_baseline")
gens = [s["generation"] for s in e1]

fig, axes = plt.subplots(1, 2, figsize=(12, 4))

ax = axes[0]
for fam in FAMILIES:
    wr = [s["family_win_rates"].get(fam, 0) for s in e1]
    ax.plot(gens, wr, color=PALETTE[fam], lw=2, label=fam)
ax.axhline(0.5, color="grey", ls="--", lw=1, alpha=0.5)
ax.set_xlabel("Generation"); ax.set_ylabel("Win rate")
ax.set_title("Family Win Rates over 50 Generations")
ax.set_ylim(0, 1); ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

ax = axes[1]
div = [s["population_diversity"] for s in e1]
ax.plot(gens, div, color="#333", lw=2)
ax.set_xlabel("Generation"); ax.set_ylabel("Population diversity (mean CV)")
ax.set_title("Genome Diversity over Time")
ax.set_ylim(0, 1)
ax.spines[["top","right"]].set_visible(False)

plt.tight_layout(); plt.show()
print("Key finding: setup starts as the strongest family at gen 5 (0.69) but declines")
print("steadily to 0.44 by gen 50.  Greedy compounds; setup front-loads its advantage.")
""")

# ===========================================================================
# SECTION 4 — GENOME EVOLUTION
# ===========================================================================

md("""\
## 4 · Genome Evolution: What Are Agents Actually Learning?

Each agent has a genome — a vector of continuous behavioural parameters.
Genomes mutate within their family at rate σ per generation and are selected by win rate.
We run three mutation rate variants on a greedy-only population to isolate the genome
dynamics from inter-family competition.

> **Pre-computed:** `data/experiments/exp4_*.json` — 20 greedy agents, 50 gens each.
""")

code("""\
e4_low = load_exp("exp4_low_0.01")
e4_med = load_exp("exp4_med_0.05")
e4_hi  = load_exp("exp4_high_0.20")

gens4 = [s["generation"] for s in e4_low]

fig, axes = plt.subplots(1, 2, figsize=(12, 4))

# aggression trajectory
ax = axes[0]
for snaps, label, ls in [
    (e4_low, "σ = 0.01 (low)",  "-"),
    (e4_med, "σ = 0.05 (med)",  "-"),
    (e4_hi,  "σ = 0.20 (high)", "--"),
]:
    agg = [s["mean_genomes"]["greedy"]["aggression"] for s in snaps]
    ax.plot(gens4, agg, ls=ls, lw=2, label=label)
ax.set_xlabel("Generation"); ax.set_ylabel("Mean aggression parameter")
ax.set_title("Aggression Convergence by Mutation Rate")
ax.set_ylim(0.5, 1.05); ax.legend(frameon=False)
ax.axhline(1.0, color="grey", ls=":", lw=1, alpha=0.6)
ax.spines[["top","right"]].set_visible(False)

# diversity
ax = axes[1]
for snaps, label, ls in [
    (e4_low, "σ = 0.01 (low)",  "-"),
    (e4_med, "σ = 0.05 (med)",  "-"),
    (e4_hi,  "σ = 0.20 (high)", "--"),
]:
    div = [s["population_diversity"] for s in snaps]
    ax.plot(gens4, div, ls=ls, lw=2, label=label)
ax.set_xlabel("Generation"); ax.set_ylabel("Population diversity (mean CV)")
ax.set_title("Diversity by Mutation Rate")
ax.set_ylim(0, 0.8); ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

plt.tight_layout(); plt.show()
print("All three mutation rates converge to high aggression (~0.94).")
print("Low mutation locks in fastest but explores least (diversity = 0.13 at gen 50).")
print("High mutation reaches the same endpoint with a much wider, noisier search.")
""")

code("""\
# ── radar chart: greedy genome at gen 0 vs gen 50 (medium mutation) ──────────
import numpy as np

PARAMS  = ["aggression", "status_priority", "setup_willingness",
           "protect_threshold", "hp_heal_threshold", "item_use_chance",
           "switch_threshold", "uncertainty"]
LABELS  = ["aggression", "status\npriority", "setup\nwilling.", "protect\nthresh.",
           "hp_heal\nthresh.", "item_use\nchance", "switch\nthresh.", "uncertainty"]
SCALES  = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0]  # uncertainty lives in [0,0.5]→*2

def genome_vals(genome_dict: dict, params=PARAMS, scales=SCALES) -> list[float]:
    return [genome_dict.get(p, 0) * s for p, s in zip(params, scales)]

N = len(PARAMS)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]

fig, axes = plt.subplots(1, 3, figsize=(13, 4.5),
                          subplot_kw=dict(polar=True))

labels_with_rate = ["σ=0.01", "σ=0.05", "σ=0.20"]
for ax, snaps, lbl in zip(axes, [e4_low, e4_med, e4_hi], labels_with_rate):
    g0  = genome_vals(snaps[0]["mean_genomes"]["greedy"])
    g50 = genome_vals(snaps[-1]["mean_genomes"]["greedy"])
    v0  = g0  + [g0[0]]
    v50 = g50 + [g50[0]]

    ax.plot(angles, v0,  "o--", color="grey",             lw=1.5, alpha=0.7, label="Gen 0")
    ax.fill(angles, v0,          color="grey",             alpha=0.08)
    ax.plot(angles, v50, "o-",  color=PALETTE["greedy"],  lw=2,              label="Gen 50")
    ax.fill(angles, v50,         color=PALETTE["greedy"],  alpha=0.18)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(LABELS, size=7.5)
    ax.set_ylim(0, 1.05)
    ax.set_title(lbl, pad=14, fontsize=11)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=8, frameon=False)

plt.suptitle("Greedy Genome: Gen 0 → Gen 50  (all parameters normalised to [0, 1])",
             y=1.03, fontsize=12)
plt.tight_layout()
plt.show()
print("Aggression expands toward the boundary in all three runs.")
print("Status priority and uncertainty collapse — the genome learns to ignore them.")
""")

# ===========================================================================
# SECTION 5 — ROSTER DRIFT & WHAT EVOLUTION SELECTED
# ===========================================================================

md("""\
## 5 · Roster Drift: What Pokémon Did Evolution Select For?

Rosters evolve separately from genomes. Each generation the Pokémon with the worst
family-specific fitness signal (fewest KOs for greedy, fewest turns survived for stall,
fewest stat stages for setup, random for random) is cut and replaced by a
fitness-proportionate sample from the global pool.

> **Pre-computed:** `data/experiments/exp5_bst_drift.json` and
> `data/experiments/pokemon_analysis.json`.
""")

code("""\
e5   = load_exp("exp5_bst_drift")
poke = load_exp("pokemon_analysis")

gens5 = [s["generation"] for s in e5]

# ── BST trajectory ────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

ax = axes[0]
for fam in FAMILIES:
    bst = [s["mean_roster_bst"].get(fam, 0) for s in e5]
    ax.plot(gens5, bst, color=PALETTE[fam], lw=2, label=fam)
ax.set_xlabel("Generation"); ax.set_ylabel("Mean roster BST")
ax.set_title("Roster BST Drift over 50 Generations")
ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

# ── BST histogram: gen 0 vs gen 50 ───────────────────────────────────────────
ax = axes[1]
g0_hist  = poke["gen0_bst_histogram"]
g50_hist = poke["final_bst_histogram"]
buckets  = sorted(set(g0_hist) | set(g50_hist),
                  key=lambda b: int(b.split("-")[0]))
x  = np.arange(len(buckets))
w  = 0.38
b0 = [g0_hist.get(b, 0)  for b in buckets]
b50= [g50_hist.get(b, 0) for b in buckets]
ax.bar(x - w/2, b0,  w, label="Gen 0",  color="#aec7e8", edgecolor="white")
ax.bar(x + w/2, b50, w, label="Gen 50", color="#1f77b4", edgecolor="white")
ax.set_xticks(x); ax.set_xticklabels(buckets, rotation=35, ha="right", fontsize=8)
ax.set_xlabel("BST range"); ax.set_ylabel("Roster slots occupied")
ax.set_title("BST Distribution: Gen 0 vs Gen 50")
ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

plt.tight_layout(); plt.show()
print(f"650–699 tier: {g0_hist.get('650-699', 0)} slots at gen 0 → "
      f"{g50_hist.get('650-699', 0)} at gen 50  (+{g50_hist.get('650-699',0)-g0_hist.get('650-699',0)})")
print(f"300–399 tier: {sum(g0_hist.get(b,0) for b in ['300-349','350-399'])} → "
      f"{sum(g50_hist.get(b,0) for b in ['300-349','350-399'])}  (nearly eliminated)")
""")

code("""\
# ── type distribution shift ───────────────────────────────────────────────────
g0_types  = poke["gen0_roster"]["type_distribution"]
g50_types = poke["final_roster"]["type_distribution"]
all_types = sorted(set(g0_types) | set(g50_types),
                   key=lambda t: g50_types.get(t, 0), reverse=True)[:12]

fig, ax = plt.subplots(figsize=(9, 4.5))
y  = np.arange(len(all_types))
w  = 0.38
ax.barh(y + w/2, [g0_types.get(t, 0)  for t in all_types], w,
        label="Gen 0",  color="#aec7e8", edgecolor="white")
ax.barh(y - w/2, [g50_types.get(t, 0) for t in all_types], w,
        label="Gen 50", color="#1f77b4", edgecolor="white")
ax.set_yticks(y); ax.set_yticklabels(all_types)
ax.set_xlabel("Total type slots across all rosters")
ax.set_title("Type Distribution Shift: Gen 0 → Gen 50")
ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

for t, yi in zip(all_types, y):
    delta = g50_types.get(t, 0) - g0_types.get(t, 0)
    ax.text(max(g0_types.get(t,0), g50_types.get(t,0)) + 0.5, yi,
            f"{delta:+d}", va="center", fontsize=8, color="#333")

plt.tight_layout(); plt.show()
print("Steel +14, Fire +13: resistance-heavy and offensively broad types dominate.")
print("Grass −17, Psychic −10, Rock −10: types with many weaknesses or poor coverage are purged.")
""")

# ===========================================================================
# SECTION 6 — ENVIRONMENTAL VARIABLES
# ===========================================================================

md("""\
## 6 · Environmental Variables: Items and Weather

The battle environment is an experimental parameter. Two sub-experiments show
that it reshapes family fortunes in non-obvious ways — demonstrating that there
is no universally dominant strategy, only contextually dominant ones.

> **Pre-computed:** `data/experiments/exp2_items.json` and
> `data/experiments/exp3_weather_*.json` — 8 agents/family, 50 gens each.
""")

code("""\
# ── items: baseline vs items at gen 50 ───────────────────────────────────────
e2 = load_exp("exp2_items")

baseline_wr = e1[-1]["family_win_rates"]
items_wr    = e2[-1]["family_win_rates"]

fig, ax = plt.subplots(figsize=(7, 4))
x  = np.arange(len(FAMILIES))
w  = 0.38
ax.bar(x - w/2, [baseline_wr.get(f, 0) for f in FAMILIES], w,
       color=[PALETTE[f] for f in FAMILIES], alpha=0.55, label="Baseline (no items)", edgecolor="white")
ax.bar(x + w/2, [items_wr.get(f, 0)    for f in FAMILIES], w,
       color=[PALETTE[f] for f in FAMILIES], alpha=1.0,  label="With items", edgecolor="white")
ax.set_xticks(x); ax.set_xticklabels(FAMILIES)
ax.set_ylabel("Win rate at gen 50")
ax.set_title("Effect of Bag Items on Family Win Rates")
ax.axhline(0.5, color="grey", ls="--", lw=0.8, alpha=0.5)
ax.set_ylim(0, 1)
ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

for i, fam in enumerate(FAMILIES):
    delta = items_wr.get(fam, 0) - baseline_wr.get(fam, 0)
    ax.text(i + w/2, items_wr.get(fam,0) + 0.015, f"{delta:+.2f}",
            ha="center", va="bottom", fontsize=8, color="#333")

plt.tight_layout(); plt.show()
print("Setup benefits most from items (+0.16): X Attack accelerates its boost-then-sweep plan.")
print("Stall is hurt (−0.10): opponents can heal through its attrition with Hyper Potions.")
""")

code("""\
# ── weather: family win rates at gen 50 across all conditions ────────────────
WEATHERS = ["none", "sun", "rain", "sand", "hail"]

weather_wr = {"none": e1[-1]["family_win_rates"]}
for w in WEATHERS[1:]:
    snaps = load_exp(f"exp3_weather_{w}")
    weather_wr[w] = snaps[-1]["family_win_rates"]

wr_df = pd.DataFrame(
    {w: {f: weather_wr[w].get(f, 0) for f in FAMILIES} for w in WEATHERS}
).T[FAMILIES]

fig, ax = plt.subplots(figsize=(9, 4))
x  = np.arange(len(WEATHERS))
w_width = 0.18
offsets = np.linspace(-(len(FAMILIES)-1)/2, (len(FAMILIES)-1)/2, len(FAMILIES)) * w_width
for fam, offset in zip(FAMILIES, offsets):
    ax.bar(x + offset, wr_df[fam], w_width,
           color=PALETTE[fam], label=fam, edgecolor="white")
ax.set_xticks(x); ax.set_xticklabels(WEATHERS)
ax.set_ylabel("Win rate at gen 50")
ax.set_title("Family Win Rates by Weather Condition")
ax.axhline(0.5, color="grey", ls="--", lw=0.8, alpha=0.5)
ax.set_ylim(0, 1)
ax.legend(frameon=False, ncol=4, loc="upper right")
ax.spines[["top","right"]].set_visible(False)
plt.tight_layout(); plt.show()
print("Sand is the only condition where greedy does NOT dominate — setup wins at 0.565 vs greedy 0.520.")
print("Hail narrows the gap most, lifting random to 0.35 (its best showing across all experiments).")
""")

# ===========================================================================
# SECTION 7 — MINIMAX
# ===========================================================================

md("""\
## 7 · Minimax: Can Evolution Overtake Optimal Play?

A fixed **minimax** agent (one-ply lookahead over all action pairs) is added to the
population as a reference. It does not reproduce and its roster never evolves.
It starts with the highest win rate of any agent at generation 1 — and then falls.

> **Pre-computed:** `data/experiments/exp6_minimax.json` — 8 agents/family + 2 minimax, 50 gens.
""")

code("""\
e6   = load_exp("exp6_minimax")
gens6 = [s["generation"] for s in e6]

fig, axes = plt.subplots(1, 2, figsize=(13, 4))

# win rate trajectories
ax = axes[0]
for fam in FAMILIES:
    wr = [s["family_win_rates"].get(fam, 0) for s in e6]
    ax.plot(gens6, wr, color=PALETTE[fam], lw=2, label=fam)
mm_wr = [s["family_win_rates"].get("minimax", 0) for s in e6]
ax.plot(gens6, mm_wr, color=PALETTE["minimax"], lw=2.5, ls="--", label="minimax (fixed)")

# annotate the nadir
nadir_gen = gens6[mm_wr.index(min(mm_wr))]
nadir_val = min(mm_wr)
ax.annotate(f"nadir {nadir_val:.2f}", xy=(nadir_gen, nadir_val),
            xytext=(nadir_gen + 3, nadir_val - 0.06),
            arrowprops=dict(arrowstyle="->", color="#555"), fontsize=8, color="#555")

ax.axhline(0.5, color="grey", ls=":", lw=1, alpha=0.5)
ax.set_xlabel("Generation"); ax.set_ylabel("Win rate")
ax.set_title("Win Rates — Evolved Families vs Fixed Minimax")
ax.set_ylim(0, 1); ax.legend(frameon=False, fontsize=8)
ax.spines[["top","right"]].set_visible(False)

# BST comparison
ax = axes[1]
for fam in FAMILIES:
    bst = [s["mean_roster_bst"].get(fam, 0) for s in e6]
    ax.plot(gens6, bst, color=PALETTE[fam], lw=2, label=fam)
mm_bst = [s["mean_roster_bst"].get("minimax", 0) for s in e6]
ax.plot(gens6, mm_bst, color=PALETTE["minimax"], lw=2.5, ls="--", label="minimax (frozen)")
ax.set_xlabel("Generation"); ax.set_ylabel("Mean roster BST")
ax.set_title("Roster BST: Evolved Families vs Frozen Minimax")
ax.legend(frameon=False, fontsize=8)
ax.spines[["top","right"]].set_visible(False)

plt.tight_layout(); plt.show()
print("Minimax enters at gen 1 as the strongest agent (0.71) and finishes at 0.42.")
print("Its BST is frozen at ~490 while evolved families reach 580–600.")
print("The BST gap explains ~60% of its decline; the rest is co-evolutionary pressure.")
""")

# ===========================================================================
# SECTION 8 — POKEMON & MOVE ANALYSIS
# ===========================================================================

md("""\
## 8 · What Did Evolution Actually Select?

Zoom in on *which* Pokémon and *which* moves evolution kept, cut, and used most.
This section cross-checks the simulation against real-world competitive Pokémon
knowledge — if the model is mechanically sound, evolution should find what
competitive play independently determined to be strong.

> **Pre-computed:** `data/experiments/pokemon_analysis.json` — 50-gen baseline run
> with full per-Pokémon and per-move tracking on the final generation.
""")

code("""\
# ── top KO dealers ────────────────────────────────────────────────────────────
top_kos = poke["final_gen_performance"]["top_10_by_kos"]
top_surv = poke["final_gen_performance"]["top_10_by_survival"]

fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

for ax, data, metric, title in [
    (axes[0], top_kos,  "kos",          "Top Pokémon by KOs Dealt (final generation)"),
    (axes[1], top_surv, "turns_active", "Top Pokémon by Turns Survived"),
]:
    names  = [f"{p['name']}\\n({'/'.join(p['types'])})" for p in data]
    values = [p[metric] for p in data]
    colors = [PALETTE.get(p["family"], "#aaa") for p in data]
    y = np.arange(len(names))
    ax.barh(y, values, color=colors, edgecolor="white")
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel(metric.replace("_", " ").title())
    ax.set_title(title, fontsize=10)
    ax.invert_yaxis()
    ax.spines[["top","right"]].set_visible(False)

patches = [mpatches.Patch(color=PALETTE[f], label=f) for f in FAMILIES]
axes[1].legend(handles=patches, fontsize=8, frameon=False, loc="lower right")
plt.tight_layout(); plt.show()
print("Yveltal (Dark/Flying, BST 680) leads KOs for stall — a Gen 6 Uber.")
print("Aegislash (Steel/Ghost, BST 500) tops survival AND KOs — independently banned from OU in Gen 6.")
""")

code("""\
# ── move usage breakdown ─────────────────────────────────────────────────────
top_moves = poke["final_gen_moves"]["top_moves_by_usage"][:15]
cat_totals = poke["final_gen_moves"]["category_usage_totals"]
type_totals = poke["final_gen_moves"]["type_usage_totals"]

fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))

# top moves bar
ax = axes[0]
names  = [m["name"] for m in top_moves]
usages = [m["usage"] for m in top_moves]
cat_colors = {"physical": "#e15759", "special": "#4e79a7", "status": "#59a14f"}
colors = [cat_colors.get(m.get("category", ""), "#aaa") for m in top_moves]
y = np.arange(len(names))
ax.barh(y, usages, color=colors, edgecolor="white")
ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8)
ax.set_xlabel("Times used"); ax.set_title("Top 15 Moves by Usage", fontsize=10)
ax.invert_yaxis()
ax.spines[["top","right"]].set_visible(False)
patches = [mpatches.Patch(color=c, label=l) for l, c in cat_colors.items()]
ax.legend(handles=patches, fontsize=7, frameon=False)

# category pie
ax = axes[1]
labels = list(cat_totals.keys())
sizes  = list(cat_totals.values())
colors2 = [cat_colors.get(l, "#aaa") for l in labels]
ax.pie(sizes, labels=labels, colors=colors2, autopct="%1.0f%%",
       startangle=90, textprops={"fontsize": 9})
ax.set_title("Move Category Breakdown\n(actual battle usage)", fontsize=10)

# top types
ax = axes[2]
top_types = list(type_totals.items())[:10]
tnames = [t[0] for t in top_types]
tvals  = [t[1] for t in top_types]
y2 = np.arange(len(tnames))
ax.barh(y2, tvals, color="#6baed6", edgecolor="white")
ax.set_yticks(y2); ax.set_yticklabels(tnames, fontsize=9)
ax.set_xlabel("Total usage"); ax.set_title("Top Move Types by Usage", fontsize=10)
ax.invert_yaxis()
ax.spines[["top","right"]].set_visible(False)

plt.tight_layout(); plt.show()
print("Roost (#3, 670 uses) and Protect (#5, 544 uses) confirm stall agents")
print("are actually executing their strategy, not just attacking.")
print("Flying and Dragon dominate move types — matching the legendaries evolution selected.")
""")

# ===========================================================================
# SECTION 9 — LIVE MINI-EXPERIMENT
# ===========================================================================

md("""\
## 9 · Live Mini-Experiment

Adjust the parameters below and re-run the cell to see a fresh evolutionary trajectory.
Keep `GENS ≤ 15` and `AGENTS_PER_FAMILY ≤ 6` to stay under ~30 seconds.

> ⚠️ **Runtime warning:** this cell runs a live simulation — expect 10–30 seconds
> depending on the parameters chosen.
""")

code("""\
# ── ADJUSTABLE PARAMETERS ────────────────────────────────────────────────────
GENS             = 10    # generations to run
MUTATION_RATE    = 0.05  # genome mutation rate
AGENTS_PER_FAM   = 5     # agents per family (total = 4×)
BAG              = {}    # e.g. {"Hyper Potion": 2, "X Attack": 1}
SEED             = 99
# ─────────────────────────────────────────────────────────────────────────────

import time
rng_mini = random.Random(SEED)
random.seed(SEED)

pop = make_population(
    {FamilyType.GREEDY: AGENTS_PER_FAM, FamilyType.STALL: AGENTS_PER_FAM,
     FamilyType.SETUP:  AGENTS_PER_FAM, FamilyType.RANDOM: AGENTS_PER_FAM},
    roster,
    initial_bag=BAG,
    rng=rng_mini,
)

t0 = time.time()
snaps = pop.run(generations=GENS, mutation_rate=MUTATION_RATE)
print(f"Done in {time.time()-t0:.1f}s")

gens_live = [s.generation for s in snaps]

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
ax = axes[0]
for fam in FAMILIES:
    wr = [s.family_win_rates.get(fam, 0) for s in snaps]
    ax.plot(gens_live, wr, color=PALETTE[fam], lw=2, label=fam)
ax.axhline(0.5, color="grey", ls="--", lw=0.8, alpha=0.5)
ax.set_xlabel("Generation"); ax.set_ylabel("Win rate")
ax.set_title(f"Mini-Tournament  (pop={AGENTS_PER_FAM*4}, σ={MUTATION_RATE}, seed={SEED})")
ax.set_ylim(0, 1); ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

ax = axes[1]
for fam in FAMILIES:
    bst = [s.mean_roster_bst.get(fam, 0) for s in snaps]
    ax.plot(gens_live, bst, color=PALETTE[fam], lw=2, label=fam)
ax.set_xlabel("Generation"); ax.set_ylabel("Mean roster BST")
ax.set_title("Roster BST Drift (live)")
ax.legend(frameon=False)
ax.spines[["top","right"]].set_visible(False)

plt.tight_layout(); plt.show()
""")

# ===========================================================================
# SECTION 10 — DISCUSSION
# ===========================================================================

md("""\
## 10 · Discussion

### Connection to *Think Complexity* Ch. 12

Downey's evolution-of-cooperation model asks: in a well-mixed population without memory,
can cooperators (Tit-for-Tat, Always Cooperate) persist against defectors
(Always Defect)? The answer is usually no — Always Defect fixates unless spatial
structure or iterated interaction creates a selective pressure for cooperation.

Our Pokémon ABM recapitulates this result in a mechanically richer setting:

- **Greedy ≈ Always Defect.** It extracts maximum value each turn, ignores long-term
  position, and ends up dominating most environments.
- **Stall ≈ Always Cooperate (passive).** It survives by not fighting — a passive strategy
  that loses to pure aggression unless the aggressor can't break through.
- **Setup ≈ Tit-for-Tat (patient).** It builds position before striking. It outperforms
  greedy early (gen 5: setup=0.69, greedy=0.59) but *declines over evolutionary time*
  as greedy populations converge to maximum aggression, closing the window for safe setup.

### Key Findings

1. **Greedy dominance is not immediate** — setup leads at gen 5, then falls monotonically
   to 0.44 by gen 50 as greedy genomes converge to aggression ≈ 0.94.

2. **Genome evolution finds a clear signal** — all mutation rates converge to high
   aggression. Low mutation locks in fast but gets stuck in a suboptimum; medium
   mutation finds the true attractor; high mutation reaches the same endpoint noisily.

3. **Environment shapes dominance** — sand is the only condition where greedy is not
   dominant (setup wins 0.565 vs greedy 0.520). Items benefit setup (+16pp) by
   accelerating its boost accumulation. Weather and items function as the "spatial
   structure" that allows non-greedy strategies to persist in Downey's framing.

4. **Roster evolution validates the simulation** — evolution independently selected
   Pokémon that Gen 6 competitive play flagged as broken (Aegislash, Yveltal, Dialga).
   Steel and Fire types rose; Grass, Rock, and Psychic fell — matching the competitive
   metagame reasoning based on type coverage.

5. **Fixed optimal play loses to co-evolution** — minimax enters as the strongest
   agent (0.71) and falls to 0.42 as evolved families co-adapt and their BSTs
   outgrow minimax's frozen roster (490 BST vs 580–600 for evolved families by gen 50).

### Limitations and Future Directions

- Population size (8/family) keeps runs fast but produces per-generation noise.
  Larger populations would give tighter win-rate trajectories.
- Only four families were studied; adding hybrids or genome crossover between families
  would test whether behavioral identities are stable under interbreeding pressure.
- Weather was fixed for entire runs; dynamic weather (changing mid-battle or mid-generation)
  might sustain diversity differently.
""")

# ===========================================================================
# EMIT NOTEBOOK
# ===========================================================================

notebook = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
            "version": "3.11.0",
        },
    },
    "cells": cells,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(notebook, f, indent=1)

print(f"Wrote {len(cells)} cells to {OUT}")

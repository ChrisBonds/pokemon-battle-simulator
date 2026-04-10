# Pokémon Battle ABM — CLAUDE.md

## Project Overview
Agent-based model of 1v1 Pokémon battles using high-fidelity mechanics (types, stats, move effects).
Built for ENGG*3130 Modelling Complex Systems at University of Guelph. Due April 19, 2026.

Deliverables:
- PDF report (ACM format, max 8 pages + references page)
- Jupyter notebook demo (`notebooks/demo.ipynb`)
- `environment.yml` for dependencies

## Architecture

```
pokemon_battle_sim/
├── data/                  # Static JSON/CSV — fetched once from PokéAPI, committed to repo
├── scripts/
│   └── fetch_data.py      # One-time script to pull from PokéAPI and dump to data/
├── simulator/
│   ├── __init__.py
│   ├── data_loader.py     # Loads from data/ folder, never calls API at runtime
│   ├── type_chart.py      # Type effectiveness lookup table
│   ├── move.py            # Move class (power, type, effect, accuracy)
│   ├── pokemon.py         # Pokemon class (stats, moves, current HP, status conditions)
│   ├── trainer.py         # Trainer/Agent class — strategy and decision-making lives here
│   └── battle.py          # Battle engine — turn loop, damage formula, win condition
└── notebooks/
    └── demo.ipynb
```

**Key design principle:** `battle.py` is a dumb mechanical engine. All interesting agent behavior
plugs in through `trainer.py`. Keep them decoupled.

## Data Strategy
- Pokémon data comes from PokéAPI, fetched once via `scripts/fetch_data.py` and stored as
  static JSON/CSV in `data/`
- **Never call PokéAPI at runtime** — notebook cells must run in a few seconds
- If adding new Pokémon or moves, re-run `fetch_data.py` and commit the updated data files

## Hard Constraints (from rubric)
- All notebook cells must execute in a few seconds on a normal laptop
- If any simulation takes longer, add a warning comment in the cell
- Report max 8 pages + 1 page references only
- At least 3 references to published papers or book sections

## Style Guide
- Type hints on function signatures, skip them elsewhere
- One-line docstrings only unless a function is genuinely non-obvious
- No inline comments unless something would be confusing without one
- `black` for formatting (default settings)
- This is a student project — don't over-engineer it

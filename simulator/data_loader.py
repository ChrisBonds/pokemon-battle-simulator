"""Load Pokémon and move data from static JSON files in data/."""

from __future__ import annotations

import json
import os

from simulator.move import Move
from simulator.pokemon import Pokemon


def load_moves(path: str) -> dict[str, Move]:
    """Load moves.json and return a dict keyed by move name."""
    with open(path) as f:
        raw = json.load(f)

    moves: dict[str, Move] = {}
    for entry in raw:
        m = Move(
            name=entry["name"],
            type=entry["type"],
            power=entry.get("power"),
            accuracy=entry.get("accuracy"),
            category=entry["category"],
            priority=entry.get("priority", 0),
            secondary=entry.get("secondary") or [],
            contact=entry.get("contact", True),
            switch_after=entry.get("switch_after", False),
        )
        moves[m.name] = m
    return moves


def load_pokemon(path: str, moves_by_name: dict[str, Move]) -> list[Pokemon]:
    """Load pokemon.json and return instantiated Pokemon objects.

    Supports both new format (move_pool) and old format (moves).
    move_pool is stored on each Pokemon; team builder samples 4 into moveset.
    """
    with open(path) as f:
        raw = json.load(f)

    roster: list[Pokemon] = []
    for entry in raw:
        # Support both new (move_pool) and old (moves) field names
        pool_names: list[str] = entry.get("move_pool") or entry.get("moves") or []

        pool: list[Move] = []
        for move_name in pool_names:
            if move_name not in moves_by_name:
                # Stale data: move exists in pokemon.json but not moves.json — skip with warning
                print(f"  [warn] Move {move_name!r} (pool of {entry['name']!r}) not in moves.json — skipped")
                continue
            pool.append(moves_by_name[move_name])

        # Default moveset is the first 4 from the pool; team builder overwrites this
        default_moveset = pool[:4]

        p = Pokemon(
            name=entry["name"],
            types=entry["types"],
            hp=entry["hp"],
            atk=entry["atk"],
            def_=entry["def"],
            sp_atk=entry["sp_atk"],
            sp_def=entry["sp_def"],
            spe=entry["spe"],
            moveset=default_moveset,
            held_item=entry.get("held_item"),
            nature=entry.get("nature", "Hardy"),
            evs=entry.get("evs"),
        )
        p.move_pool = pool
        p.usage_pct = entry.get("usage_pct", 1.0)
        roster.append(p)
    return roster


def load_all(data_dir: str) -> tuple[list[Pokemon], dict[str, Move]]:
    """Convenience wrapper: load both files from data_dir."""
    moves = load_moves(os.path.join(data_dir, "moves.json"))
    roster = load_pokemon(os.path.join(data_dir, "pokemon.json"), moves)
    return roster, moves

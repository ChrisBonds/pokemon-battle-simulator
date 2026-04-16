"""Item registry — held item metadata and bag item application."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.pokemon import Pokemon


@dataclass
class ItemUse:
    """A bag item action — trainer uses an item from their bag this turn."""

    item_name: str
    target: str = "self"  # all currently supported bag items target the user's active Pokémon

# Each item entry is a plain dict of flags/values.
# battle.py and trainer.py read these dicts to decide what to do.
ITEM_DATA: dict[str, dict] = {
    "Choice Band": {
        "physical_damage_mult": 1.5,
        "choice_lock": True,
    },
    "Choice Specs": {
        "special_damage_mult": 1.5,
        "choice_lock": True,
    },
    "Choice Scarf": {
        "speed_mult": 1.5,
        "choice_lock": True,
    },
    "Leftovers": {
        "end_of_turn_heal_fraction": 1 / 16,
    },
    "Life Orb": {
        "damage_mult": 1.3,
        "recoil_fraction": 1 / 10,
    },
    "Rocky Helmet": {
        "contact_recoil_fraction": 1 / 6,  # damage dealt to the attacker
    },
    "Lum Berry": {
        "cure_status_once": True,
    },
    "Black Sludge": {
        # Heals Poison-types; damages non-Poison-types
        "end_of_turn_heal_fraction_poison": 1 / 8,
        "end_of_turn_damage_fraction_other": 1 / 8,
    },
    "Assault Vest": {
        "sp_def_mult": 1.5,
        "blocks_status_moves": True,  # battle.py enforces this
    },
    "Sitrus Berry": {
        "sitrus_berry": True,
        "sitrus_heal_fraction": 0.25,  # heal 25% max HP once, consumed
    },
    "Focus Sash": {
        "focus_sash": True,  # survive one hit from full HP with 1 HP, consumed
    },
    "Expert Belt": {
        "expert_belt": True,  # 1.2× damage on super-effective hits
    },
    "Eviolite": {
        "eviolite": True,
        "def_mult": 1.5,             # reduces physical damage taken
        "sp_def_mult_eviolite": 1.5, # reduces special damage taken
    },
}


def get_item_data(name: str | None) -> dict:
    """Return held item metadata dict; empty dict if name is None or unknown."""
    if name is None:
        return {}
    return ITEM_DATA.get(name, {})


# ---------------------------------------------------------------------------
# Bag items — consumables used via ItemUse actions during battle
# ---------------------------------------------------------------------------

BAG_ITEM_DATA: dict[str, dict] = {
    "Hyper Potion": {"heal_hp": 200},
    "Full Restore":  {"heal_to_full": True, "cure_status": True},
    "X Attack":      {"stat": "atk",    "stages": 1},
    "X Sp. Atk":     {"stat": "sp_atk", "stages": 1},
    "X Defense":     {"stat": "def_",   "stages": 1},
}


def get_bag_item_data(name: str | None) -> dict:
    """Return bag item metadata dict; empty dict if name is None or unknown."""
    if name is None:
        return {}
    return BAG_ITEM_DATA.get(name, {})


def apply_item(item_name: str, pokemon: "Pokemon") -> None:
    """Apply a bag item's effect to pokemon in-place."""
    data = BAG_ITEM_DATA.get(item_name, {})
    if not data:
        return

    if data.get("heal_to_full"):
        pokemon.current_hp = pokemon.hp
    elif "heal_hp" in data:
        pokemon.current_hp = min(pokemon.hp, pokemon.current_hp + data["heal_hp"])

    if data.get("cure_status"):
        pokemon.status = None
        pokemon.badly_poison_counter = 0

    if "stat" in data:
        pokemon.apply_stage(data["stat"], data["stages"])

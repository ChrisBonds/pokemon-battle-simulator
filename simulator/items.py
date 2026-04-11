"""Item registry — metadata only; effects are applied in battle.py."""

from __future__ import annotations

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
    """Return item metadata dict; empty dict if name is None or unknown."""
    if name is None:
        return {}
    return ITEM_DATA.get(name, {})

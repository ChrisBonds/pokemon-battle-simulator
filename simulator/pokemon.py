from __future__ import annotations

import math
from typing import Optional

from simulator.move import Move

# Standard stat stage multipliers (Gen 5+)
_STAGE_MULT: dict[int, float] = {
    -6: 2 / 8, -5: 2 / 7, -4: 2 / 6, -3: 2 / 5, -2: 2 / 4, -1: 2 / 3,
     0: 1.0,
     1: 3 / 2,  2: 4 / 2,  3: 5 / 2,  4: 6 / 2,  5: 7 / 2,  6: 8 / 2,
}

_STAGE_DESC = {
    1: "rose", 2: "rose sharply", 3: "rose drastically",
    -1: "fell", -2: "fell sharply", -3: "fell drastically",
}

_STAT_KEYS = ("atk", "def_", "sp_atk", "sp_def", "spe", "acc", "eva")

# Nature → {stat: multiplier}. Only non-neutral entries listed.
_NATURE_MODS: dict[str, dict[str, float]] = {
    "Lonely": {"atk": 1.1, "def_": 0.9},
    "Brave":  {"atk": 1.1, "spe":  0.9},
    "Adamant":{"atk": 1.1, "sp_atk": 0.9},
    "Naughty":{"atk": 1.1, "sp_def": 0.9},
    "Bold":   {"def_": 1.1, "atk": 0.9},
    "Relaxed":{"def_": 1.1, "spe":  0.9},
    "Impish": {"def_": 1.1, "sp_atk": 0.9},
    "Lax":    {"def_": 1.1, "sp_def": 0.9},
    "Timid":  {"spe": 1.1,  "atk":  0.9},
    "Hasty":  {"spe": 1.1,  "def_": 0.9},
    "Jolly":  {"spe": 1.1,  "sp_atk": 0.9},
    "Naive":  {"spe": 1.1,  "sp_def": 0.9},
    "Modest": {"sp_atk": 1.1, "atk": 0.9},
    "Mild":   {"sp_atk": 1.1, "def_": 0.9},
    "Quiet":  {"sp_atk": 1.1, "spe":  0.9},
    "Rash":   {"sp_atk": 1.1, "sp_def": 0.9},
    "Calm":   {"sp_def": 1.1, "atk":  0.9},
    "Gentle": {"sp_def": 1.1, "def_": 0.9},
    "Sassy":  {"sp_def": 1.1, "spe":  0.9},
    "Careful":{"sp_def": 1.1, "sp_atk": 0.9},
}


def _calc_hp(base: int, ev: int, iv: int, level: int) -> int:
    return math.floor((2 * base + iv + math.floor(ev / 4)) * level / 100) + level + 10


def _calc_stat(base: int, ev: int, iv: int, level: int, nature_mod: float) -> int:
    return math.floor(
        (math.floor((2 * base + iv + math.floor(ev / 4)) * level / 100) + 5) * nature_mod
    )


class Pokemon:
    """A single Pokémon with stats, moves, and battle state."""

    def __init__(
        self,
        name: str,
        types: list[str],
        hp: int,
        atk: int,
        def_: int,
        sp_atk: int,
        sp_def: int,
        spe: int,
        moveset: list[Move],
        level: int = 100,
        held_item: str | None = None,
        ability: str | None = None,
        nature: str = "Hardy",
        evs: dict[str, int] | None = None,
        ivs: dict[str, int] | None = None,
    ) -> None:
        self.name = name
        self.types = types
        self.level = level
        self.nature = nature

        # Store base stats for reference
        self._base = {"hp": hp, "atk": atk, "def_": def_, "sp_atk": sp_atk, "sp_def": sp_def, "spe": spe}

        _evs = evs or {}
        _ivs = ivs or {}
        _iv_default = 31
        mods = _NATURE_MODS.get(nature, {})

        # Compute actual battle stats using the Gen 5+ formula
        self.hp     = _calc_hp(hp, _evs.get("hp", 0), _ivs.get("hp", _iv_default), level)
        self.atk    = _calc_stat(atk,    _evs.get("atk",    0), _ivs.get("atk",    _iv_default), level, mods.get("atk",    1.0))
        self.def_   = _calc_stat(def_,   _evs.get("def_",   _evs.get("def", 0)), _ivs.get("def_", _iv_default), level, mods.get("def_",   1.0))
        self.sp_atk = _calc_stat(sp_atk, _evs.get("sp_atk", 0), _ivs.get("sp_atk", _iv_default), level, mods.get("sp_atk", 1.0))
        self.sp_def = _calc_stat(sp_def, _evs.get("sp_def", 0), _ivs.get("sp_def", _iv_default), level, mods.get("sp_def", 1.0))
        self.spe    = _calc_stat(spe,    _evs.get("spe",    0), _ivs.get("spe",    _iv_default), level, mods.get("spe",    1.0))

        # Held item / ability
        self.held_item: str | None = held_item
        self.ability: str | None = ability

        # Battle state — reset at the start of each battle
        self.current_hp: int = self.hp
        self.status: Optional[str] = None
        self.moveset: list[Move] = moveset
        self.move_pool: list[Move] = moveset  # full pool; team builder samples 4 into moveset
        self.stat_stages: dict[str, int] = {k: 0 for k in _STAT_KEYS}
        self.badly_poison_counter: int = 0
        self.is_protecting: bool = False
        self.protect_used_last_turn: bool = False

        # Battle-stat accumulators — read by evolution layer; reset each battle
        self.kos_dealt: int = 0
        self.turns_active: int = 0
        self.stat_stages_gained: int = 0
        self.move_usage: dict[str, int] = {}

    @property
    def is_fainted(self) -> bool:
        return self.current_hp <= 0

    @property
    def bst(self) -> int:
        """Base stat total — sum of all six base stats."""
        return sum(self._base.values())

    def effective_stat(self, stat: str) -> int:
        """Return stat value after applying stage multiplier."""
        base = getattr(self, stat)
        stage = self.stat_stages.get(stat, 0)
        return max(1, int(base * _STAGE_MULT[stage]))

    def apply_stage(self, stat: str, stages: int) -> str:
        """Apply a stat stage change; return a human-readable description."""
        old = self.stat_stages[stat]
        self.stat_stages[stat] = max(-6, min(6, old + stages))
        delta = self.stat_stages[stat] - old
        if delta == 0:
            return "won't go any higher!" if stages > 0 else "won't go any lower!"
        clamped = max(-3, min(3, delta))
        return _STAGE_DESC.get(clamped, "changed")

    def reset_battle_state(self) -> None:
        """Reset HP, status, stat stages, and battle-stat accumulators for a fresh battle."""
        self.current_hp = self.hp
        self.status = None
        self.stat_stages = {k: 0 for k in _STAT_KEYS}
        self.badly_poison_counter = 0
        self.is_protecting = False
        self.protect_used_last_turn = False
        self.kos_dealt = 0
        self.turns_active = 0
        self.stat_stages_gained = 0
        self.move_usage = {}

    def __repr__(self) -> str:
        types_str = "/".join(self.types)
        status_str = f", status={self.status}" if self.status else ""
        item_str = f", item={self.held_item}" if self.held_item else ""
        return (
            f"Pokemon({self.name!r}, {types_str}, "
            f"HP={self.current_hp}/{self.hp}{status_str}{item_str}, "
            f"moves={[m.name for m in self.moveset]})"
        )

from __future__ import annotations

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
        level: int = 50,
        held_item: str | None = None,
        ability: str | None = None,
    ) -> None:
        self.name = name
        self.types = types
        self.level = level

        # Base stats
        self.hp = hp
        self.atk = atk
        self.def_ = def_
        self.sp_atk = sp_atk
        self.sp_def = sp_def
        self.spe = spe

        # Held item / ability (ability is a placeholder for now)
        self.held_item: str | None = held_item
        self.ability: str | None = ability

        # Battle state — reset at the start of each battle
        self.current_hp: int = hp
        self.status: Optional[str] = None  # "burn", "paralysis", "poison", "sleep", "freeze"
        self.moveset: list[Move] = moveset
        self.stat_stages: dict[str, int] = {k: 0 for k in _STAT_KEYS}

    @property
    def is_fainted(self) -> bool:
        return self.current_hp <= 0

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
        """Reset HP, status, and stat stages for a fresh battle."""
        self.current_hp = self.hp
        self.status = None
        self.stat_stages = {k: 0 for k in _STAT_KEYS}

    def __repr__(self) -> str:
        types_str = "/".join(self.types)
        status_str = f", status={self.status}" if self.status else ""
        item_str = f", item={self.held_item}" if self.held_item else ""
        return (
            f"Pokemon({self.name!r}, {types_str}, "
            f"HP={self.current_hp}/{self.hp}{status_str}{item_str}, "
            f"moves={[m.name for m in self.moveset]})"
        )

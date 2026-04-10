from __future__ import annotations

from typing import Optional

from simulator.move import Move


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

        # Battle state
        self.current_hp: int = hp
        self.status: Optional[str] = None  # e.g. "burn", "paralysis", etc.
        self.moveset: list[Move] = moveset

    @property
    def is_fainted(self) -> bool:
        return self.current_hp <= 0

    def __repr__(self) -> str:
        types_str = "/".join(self.types)
        status_str = f", status={self.status}" if self.status else ""
        return (
            f"Pokemon({self.name!r}, {types_str}, "
            f"HP={self.current_hp}/{self.hp}{status_str}, "
            f"moves={[m.name for m in self.moveset]})"
        )

from __future__ import annotations

from typing import Literal


Category = Literal["physical", "special", "status"]


class Move:
    """A single Pokémon move."""

    def __init__(
        self,
        name: str,
        type: str,
        power: int | None,
        accuracy: int | None,
        category: Category,
        priority: int = 0,
        secondary: list[dict] | None = None,
        contact: bool = True,
        switch_after: bool = False,
    ) -> None:
        self.name = name
        self.type = type
        self.power = power        # None for status moves
        self.accuracy = accuracy  # None means always hits
        self.category = category
        self.priority = priority  # Quick Attack = +1, ExtremeSpeed = +2
        self.secondary = secondary or []  # list of effect dicts
        self.contact = contact and category == "physical"  # only physical can be contact
        self.switch_after = switch_after  # U-turn / Volt Switch

    def __repr__(self) -> str:
        pwr = self.power if self.power is not None else "—"
        acc = f"{self.accuracy}%" if self.accuracy is not None else "∞"
        pri = f", pri={self.priority:+d}" if self.priority != 0 else ""
        return f"Move({self.name!r}, type={self.type}, cat={self.category}, pwr={pwr}, acc={acc}{pri})"

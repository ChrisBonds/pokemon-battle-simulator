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
    ) -> None:
        self.name = name
        self.type = type
        self.power = power        # None for status moves
        self.accuracy = accuracy  # None means always hits
        self.category = category

    @property
    def is_fainted(self):
        raise AttributeError("Move has no is_fainted; did you mean Pokemon?")

    def __repr__(self) -> str:
        pwr = self.power if self.power is not None else "—"
        acc = f"{self.accuracy}%" if self.accuracy is not None else "∞"
        return f"Move({self.name!r}, type={self.type}, cat={self.category}, pwr={pwr}, acc={acc})"

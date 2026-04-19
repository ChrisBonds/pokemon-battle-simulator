"""Secondary move effect resolver."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.move import Move
    from simulator.pokemon import Pokemon


def apply_secondary(move: "Move", attacker: "Pokemon", defender: "Pokemon", battle) -> None:
    """Roll and apply each secondary effect in move.secondary."""
    for effect in move.secondary:
        if random.random() > effect.get("chance", 1.0):
            continue

        target_name = effect.get("target", "foe")
        target = attacker if target_name == "self" else defender

        if "inflict" in effect:
            _apply_status(effect["inflict"], target, battle)

        if "stat" in effect:
            stat = effect["stat"]
            stages = effect["stages"]
            desc = target.apply_stage(stat, stages)
            attacker.stat_stages_gained += abs(stages)
            stat_display = stat.replace("_", "").upper()
            battle._emit(f"  {target.name}'s {stat_display} {desc}")


def _apply_status(status: str, target: "Pokemon", battle) -> None:
    """Inflict a status condition if the target is eligible."""
    if target.is_fainted:
        return
    if target.status is not None:
        return  # already has a status

    # Type immunities
    if status == "burn" and "fire" in target.types:
        return
    if status == "freeze" and "ice" in target.types:
        return
    if status in ("poison", "badly_poison") and (
        "poison" in target.types or "steel" in target.types
    ):
        return
    if status == "paralysis" and "electric" in target.types:
        return

    target.status = status
    battle._emit(f"  {target.name} was inflicted with {status}!")

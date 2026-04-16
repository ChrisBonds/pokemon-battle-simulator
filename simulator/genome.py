"""Genome dataclass and mutation logic for evolutionary agents."""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from enum import Enum


class FamilyType(Enum):
    GREEDY = "greedy"
    STALL = "stall"
    SETUP = "setup"
    RANDOM = "random"


@dataclass
class Genome:
    # Universal parameters
    switch_threshold: float = 0.5       # type-eff floor before considering a switch
    hp_heal_threshold: float = 0.4      # HP fraction that triggers healing / safety check
    item_use_chance: float = 0.5        # probability of using an item when conditions are met

    # Greedy family
    uncertainty: float = 0.0            # σ for noisy damage estimation
    aggression: float = 0.8             # probability of picking best move vs random

    # Stall family
    protect_threshold: float = 0.25     # damage fraction taken last turn triggering Protect
    status_priority: float = 0.7        # weight toward inflicting status conditions

    # Setup family
    setup_willingness: float = 0.5      # probability of setting up when conditions allow
    boost_threshold: int = 2            # offensive stage at which agent stops setting up


# Per-family bounds for identity-preserving parameters.
# Parameters not listed here are clamped only to their global valid range.
_IDENTITY_BOUNDS: dict[FamilyType, dict[str, tuple]] = {
    FamilyType.GREEDY: {
        "aggression": (0.5, 1.0),
    },
    FamilyType.STALL: {
        "status_priority": (0.4, 1.0),
        "protect_threshold": (0.1, 0.7),
    },
    FamilyType.SETUP: {
        "setup_willingness": (0.25, 1.0),
        "boost_threshold": (2, 6),
    },
    FamilyType.RANDOM: {},
}

# Global valid ranges for all continuous parameters.
_GLOBAL_BOUNDS: dict[str, tuple[float, float]] = {
    "switch_threshold":  (0.0, 1.0),
    "hp_heal_threshold": (0.0, 1.0),
    "item_use_chance":   (0.0, 1.0),
    "uncertainty":       (0.0, 0.5),
    "aggression":        (0.0, 1.0),
    "protect_threshold": (0.0, 1.0),
    "status_priority":   (0.0, 1.0),
    "setup_willingness": (0.0, 1.0),
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def mutate(genome: Genome, mutation_rate: float, family: FamilyType) -> Genome:
    """Return a new Genome with Gaussian noise applied to continuous params.

    Identity-preserving bounds for the given family are enforced after mutation,
    ensuring family behavioral identity cannot drift away over generations.
    """
    identity_bounds = _IDENTITY_BOUNDS.get(family, {})

    def _mutate_float(param_name: str, current_value: float) -> float:
        noisy = current_value + random.gauss(0.0, mutation_rate)
        global_low, global_high = _GLOBAL_BOUNDS[param_name]
        noisy = _clamp(noisy, global_low, global_high)
        if param_name in identity_bounds:
            id_low, id_high = identity_bounds[param_name]
            noisy = _clamp(noisy, id_low, id_high)
        return noisy

    def _mutate_boost_threshold(current: int) -> int:
        if random.random() < mutation_rate * 2:
            delta = random.choice([-1, 1])
            new_value = current + delta
        else:
            new_value = current
        id_low, id_high = identity_bounds.get("boost_threshold", (1, 6))
        return int(_clamp(new_value, id_low, id_high))

    return replace(
        genome,
        switch_threshold=_mutate_float("switch_threshold", genome.switch_threshold),
        hp_heal_threshold=_mutate_float("hp_heal_threshold", genome.hp_heal_threshold),
        item_use_chance=_mutate_float("item_use_chance", genome.item_use_chance),
        uncertainty=_mutate_float("uncertainty", genome.uncertainty),
        aggression=_mutate_float("aggression", genome.aggression),
        protect_threshold=_mutate_float("protect_threshold", genome.protect_threshold),
        status_priority=_mutate_float("status_priority", genome.status_priority),
        setup_willingness=_mutate_float("setup_willingness", genome.setup_willingness),
        boost_threshold=_mutate_boost_threshold(genome.boost_threshold),
    )


def random_genome(family: FamilyType) -> Genome:
    """Return a genome initialised with family-appropriate starting values."""
    if family == FamilyType.GREEDY:
        return Genome(
            switch_threshold=0.45,
            hp_heal_threshold=0.35,
            item_use_chance=random.uniform(0.3, 0.7),
            uncertainty=random.uniform(0.0, 0.2),
            aggression=random.uniform(0.65, 0.95),
            protect_threshold=0.25,
            status_priority=0.2,
            setup_willingness=0.2,
            boost_threshold=3,
        )
    if family == FamilyType.STALL:
        return Genome(
            switch_threshold=random.uniform(0.6, 0.9),
            hp_heal_threshold=random.uniform(0.4, 0.6),
            item_use_chance=random.uniform(0.3, 0.7),
            uncertainty=0.0,
            aggression=0.4,
            protect_threshold=random.uniform(0.2, 0.5),
            status_priority=random.uniform(0.55, 0.9),
            setup_willingness=0.1,
            boost_threshold=4,
        )
    if family == FamilyType.SETUP:
        return Genome(
            switch_threshold=random.uniform(0.65, 0.9),
            hp_heal_threshold=random.uniform(0.35, 0.55),
            item_use_chance=random.uniform(0.4, 0.8),
            uncertainty=0.0,
            aggression=0.7,
            protect_threshold=0.15,
            status_priority=0.1,
            setup_willingness=random.uniform(0.45, 0.85),
            boost_threshold=random.randint(2, 4),
        )
    # RANDOM family
    return Genome(
        switch_threshold=random.uniform(0.2, 0.8),
        hp_heal_threshold=random.uniform(0.2, 0.6),
        item_use_chance=random.uniform(0.2, 0.8),
        uncertainty=random.uniform(0.0, 0.3),
        aggression=random.uniform(0.3, 0.9),
        protect_threshold=random.uniform(0.1, 0.5),
        status_priority=random.uniform(0.1, 0.6),
        setup_willingness=random.uniform(0.1, 0.7),
        boost_threshold=random.randint(1, 5),
    )

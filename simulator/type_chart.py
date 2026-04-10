"""Gen 6+ type effectiveness lookup (18 types)."""

from __future__ import annotations

# Only non-1× entries are stored. 0 = immune, 0.5 = not very effective, 2 = super effective.
_CHART: dict[str, dict[str, float]] = {
    "normal":   {"rock": 0.5, "ghost": 0,   "steel": 0.5},
    "fire":     {"fire": 0.5, "water": 0.5, "grass": 2,   "ice": 2,   "bug": 2,
                 "rock": 0.5, "dragon": 0.5,"steel": 2},
    "water":    {"fire": 2,   "water": 0.5, "grass": 0.5, "ground": 2,"rock": 2,
                 "dragon": 0.5},
    "electric": {"water": 2,  "electric": 0.5, "grass": 0.5, "ground": 0,
                 "flying": 2, "dragon": 0.5},
    "grass":    {"fire": 0.5, "water": 2,   "grass": 0.5, "poison": 0.5, "ground": 2,
                 "flying": 0.5, "bug": 0.5, "rock": 2,   "dragon": 0.5, "steel": 0.5},
    "ice":      {"fire": 0.5, "water": 0.5, "grass": 2,   "ice": 0.5, "ground": 2,
                 "flying": 2, "dragon": 2,  "steel": 0.5},
    "fighting": {"normal": 2, "ice": 2,     "poison": 0.5,"flying": 0.5,"psychic": 0.5,
                 "bug": 0.5,  "rock": 2,    "ghost": 0,   "dark": 2,  "steel": 2,
                 "fairy": 0.5},
    "poison":   {"grass": 2,  "poison": 0.5,"ground": 0.5,"rock": 0.5, "ghost": 0.5,
                 "steel": 0,  "fairy": 2},
    "ground":   {"fire": 2,   "electric": 2,"grass": 0.5, "poison": 2, "flying": 0,
                 "bug": 0.5,  "rock": 2,    "steel": 2},
    "flying":   {"electric": 0.5, "grass": 2, "fighting": 2, "bug": 2,
                 "rock": 0.5, "steel": 0.5},
    "psychic":  {"fighting": 2, "poison": 2, "psychic": 0.5, "dark": 0, "steel": 0.5},
    "bug":      {"fire": 0.5, "grass": 2,   "fighting": 0.5,"poison": 0.5,"flying": 0.5,
                 "psychic": 2,"ghost": 0.5, "dark": 2,   "steel": 0.5, "fairy": 0.5},
    "rock":     {"fire": 2,   "ice": 2,     "fighting": 0.5,"ground": 0.5,"flying": 2,
                 "bug": 2,    "steel": 0.5},
    "ghost":    {"normal": 0, "psychic": 2, "ghost": 2,   "dark": 0.5},
    "dragon":   {"dragon": 2, "steel": 0.5, "fairy": 0},
    "dark":     {"fighting": 0.5, "psychic": 2, "ghost": 2, "dark": 0.5, "fairy": 0.5},
    "steel":    {"fire": 0.5, "water": 0.5, "electric": 0.5, "ice": 2,  "rock": 2,
                 "steel": 0.5,"fairy": 2},
    "fairy":    {"fire": 0.5, "fighting": 2,"poison": 0.5, "dragon": 2, "dark": 2,
                 "steel": 0.5},
}


def get_effectiveness(attacking_type: str, defending_types: list[str]) -> float:
    """Return the combined type multiplier for an attack against a defender."""
    row = _CHART.get(attacking_type.lower(), {})
    mult = 1.0
    for t in defending_types:
        mult *= row.get(t.lower(), 1.0)
    return mult


def weather_modifier(move_type: str, weather: str | None) -> float:
    """Return the weather damage multiplier for a given move type."""
    if weather == "rain":
        if move_type == "water":
            return 1.5
        if move_type == "fire":
            return 0.5
    elif weather == "sun":
        if move_type == "fire":
            return 1.5
        if move_type == "water":
            return 0.5
    return 1.0


# Types immune to sand/hail chip damage
_SAND_IMMUNE = {"rock", "ground", "steel"}
_HAIL_IMMUNE = {"ice"}


def weather_chip_immune(pokemon_types: list[str], weather: str) -> bool:
    """Return True if this Pokémon is immune to end-of-turn weather chip damage."""
    types = {t.lower() for t in pokemon_types}
    if weather == "sand":
        return bool(types & _SAND_IMMUNE)
    if weather == "hail":
        return bool(types & _HAIL_IMMUNE)
    return True

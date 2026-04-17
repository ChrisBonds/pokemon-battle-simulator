"""
Stratified Gen 6 Pokémon pool builder — ~170 Pokémon across BST ranges and all 18 types.

Run once; commit data/ output to repo. Never call at battle runtime.

Usage:
    python scripts/fetch_data.py [--force] [--out-dir data/]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

POKEAPI_BASE = "https://pokeapi.co/api/v2"
REQUEST_DELAY = 0.6  # seconds between API calls — be polite

GEN6_VERSION_GROUPS = {"x-y", "omega-ruby-alpha-sapphire"}

ALL_TYPES = [
    "normal", "fire", "water", "electric", "grass", "ice",
    "fighting", "poison", "ground", "flying", "psychic", "bug",
    "rock", "ghost", "dragon", "dark", "steel", "fairy",
]

# (bst_min_inclusive, bst_max_exclusive, target_count)
BST_BINS = [
    (300,  400,  20),
    (400,  500,  60),
    (500,  580,  50),
    (580,  680,  30),
    (680, 9999,  10),
]

TARGET_PER_TYPE = 9   # aim for this many Pokémon per type across the full pool
MIN_TYPE_COVERAGE = 6  # flag if any type falls below this after selection

# Maps PokéAPI stat names → JSON output keys (base stats in pokemon.json)
POKEAPI_STAT_TO_JSON_KEY = {
    "hp": "hp",
    "attack": "atk",
    "defense": "def",
    "special-attack": "sp_atk",
    "special-defense": "sp_def",
    "speed": "spe",
}

# Maps PokéAPI stat names → secondary effect keys (must match Pokemon.stat_stages keys)
POKEAPI_STAT_TO_EFFECT_KEY = {
    "attack": "atk",
    "defense": "def_",
    "special-attack": "sp_atk",
    "special-defense": "sp_def",
    "speed": "spe",
    "accuracy": "acc",
    "evasion": "eva",
}

POKEAPI_AILMENT_TO_INTERNAL = {
    "burn": "burn",
    "paralysis": "paralysis",
    "poison": "poison",
    "badly-poisoned": "badly_poison",
    "freeze": "freeze",
    "sleep": "sleep",
}

# API move names (kebab-case) that need special display-name treatment
DISPLAY_NAME_EXCEPTIONS: dict[str, str] = {
    "u-turn": "U-turn",
    "will-o-wisp": "Will-O-Wisp",
    "soft-boiled": "Soft-Boiled",
    "kings-shield": "King's Shield",
    "double-edge": "Double-Edge",
    "v-create": "V-create",
    "x-scissor": "X-Scissor",
    "extreme-speed": "ExtremeSpeed",
    "freeze-dry": "Freeze-Dry",
    "trick-or-treat": "Trick-or-Treat",
    "baby-doll-eyes": "Baby-Doll Eyes",
    "forests-curse": "Forest's Curse",
    "lands-wrath": "Land's Wrath",
    "10000000-volt-thunderbolt": "10,000,000 Volt Thunderbolt",
    "lets-snuggle-forever": "Let's Snuggle Forever",
    "never-ending-nightmare": "Never-Ending Nightmare",
}

# Override secondary effects for moves PokéAPI cannot represent in our format.
# Keyed by display name. All other moves are derived dynamically from PokéAPI data.
SECONDARY_OVERRIDES: dict[str, list[dict]] = {
    # Heal moves (heal_fraction format not in PokéAPI)
    "Recover":      [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Roost":        [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Soft-Boiled":  [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Milk Drink":   [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Moonlight":    [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Morning Sun":  [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Slack Off":    [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Shore Up":     [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Synthesis":    [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Wish":         [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    "Heal Order":   [{"heal_fraction": 0.5, "target": "self", "chance": 1.0}],
    # Protect variants
    "Protect":          [{"protect": True, "target": "self", "chance": 1.0}],
    "Detect":           [{"protect": True, "target": "self", "chance": 1.0}],
    "King's Shield":    [{"protect": True, "target": "self", "chance": 1.0}],
    "Spiky Shield":     [{"protect": True, "target": "self", "chance": 1.0}],
    "Baneful Bunker":   [{"protect": True, "target": "self", "chance": 1.0}],
    # Pivot moves — switch_after handled by engine, no additional secondary
    "U-turn":       [],
    "Volt Switch":  [],
    "Flip Turn":    [],
    # Compound stat changes the API represents inconsistently
    "Shell Smash": [
        {"stat": "atk",    "stages":  2, "target": "self", "chance": 1.0},
        {"stat": "sp_atk", "stages":  2, "target": "self", "chance": 1.0},
        {"stat": "spe",    "stages":  2, "target": "self", "chance": 1.0},
        {"stat": "def_",   "stages": -1, "target": "self", "chance": 1.0},
        {"stat": "sp_def", "stages": -1, "target": "self", "chance": 1.0},
    ],
    "Geomancy": [
        {"stat": "sp_atk", "stages": 2, "target": "self", "chance": 1.0},
        {"stat": "sp_def", "stages": 2, "target": "self", "chance": 1.0},
        {"stat": "spe",    "stages": 2, "target": "self", "chance": 1.0},
    ],
    "Shift Gear": [
        {"stat": "atk", "stages": 1, "target": "self", "chance": 1.0},
        {"stat": "spe", "stages": 2, "target": "self", "chance": 1.0},
    ],
    "Tail Glow": [{"stat": "sp_atk", "stages": 3, "target": "self", "chance": 1.0}],
    # Self-lowering after damaging (PokéAPI target direction is unreliable for these)
    "Close Combat": [
        {"stat": "def_",   "stages": -1, "target": "self", "chance": 1.0},
        {"stat": "sp_def", "stages": -1, "target": "self", "chance": 1.0},
    ],
    "Superpower": [
        {"stat": "atk",  "stages": -1, "target": "self", "chance": 1.0},
        {"stat": "def_", "stages": -1, "target": "self", "chance": 1.0},
    ],
    "Leaf Storm":    [{"stat": "sp_atk", "stages": -2, "target": "self", "chance": 1.0}],
    "Draco Meteor":  [{"stat": "sp_atk", "stages": -2, "target": "self", "chance": 1.0}],
    "Overheat":      [{"stat": "sp_atk", "stages": -2, "target": "self", "chance": 1.0}],
    "Psycho Boost":  [{"stat": "sp_atk", "stages": -2, "target": "self", "chance": 1.0}],
    # Status infliction — override to ensure correct chance and targeting
    "Toxic":        [{"inflict": "badly_poison", "chance": 1.00, "target": "foe"}],
    "Will-O-Wisp":  [{"inflict": "burn",         "chance": 1.00, "target": "foe"}],
    "Thunder Wave": [{"inflict": "paralysis",     "chance": 1.00, "target": "foe"}],
    "Glare":        [{"inflict": "paralysis",     "chance": 1.00, "target": "foe"}],
    "Stun Spore":   [{"inflict": "paralysis",     "chance": 1.00, "target": "foe"}],
    "Sleep Powder": [{"inflict": "sleep",         "chance": 1.00, "target": "foe"}],
    "Spore":        [{"inflict": "sleep",         "chance": 1.00, "target": "foe"}],
    "Hypnosis":     [{"inflict": "sleep",         "chance": 0.60, "target": "foe"}],
    "Sing":         [{"inflict": "sleep",         "chance": 0.55, "target": "foe"}],
    "Lovely Kiss":  [{"inflict": "sleep",         "chance": 0.75, "target": "foe"}],
    "Dark Void":    [{"inflict": "sleep",         "chance": 0.80, "target": "foe"}],
    # Damaging moves with well-known secondary effects — keep explicit for correctness
    "Flamethrower": [{"inflict": "burn",      "chance": 0.10, "target": "foe"}],
    "Fire Blast":   [{"inflict": "burn",      "chance": 0.10, "target": "foe"}],
    "Flare Blitz":  [{"inflict": "burn",      "chance": 0.10, "target": "foe"}],
    "Lava Plume":   [{"inflict": "burn",      "chance": 0.30, "target": "foe"}],
    "Scald":        [{"inflict": "burn",      "chance": 0.30, "target": "foe"}],
    "Sacred Fire":  [{"inflict": "burn",      "chance": 0.50, "target": "foe"}],
    "Thunderbolt":  [{"inflict": "paralysis", "chance": 0.10, "target": "foe"}],
    "Thunder":      [{"inflict": "paralysis", "chance": 0.30, "target": "foe"}],
    "Body Slam":    [{"inflict": "paralysis", "chance": 0.30, "target": "foe"}],
    "Nuzzle":       [{"inflict": "paralysis", "chance": 1.00, "target": "foe"}],
    "Ice Beam":     [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Blizzard":     [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Ice Fang":     [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Icicle Crash": [{"inflict": "freeze",    "chance": 0.30, "target": "foe"}],
    "Freeze-Dry":   [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Sludge Bomb":  [{"inflict": "poison",    "chance": 0.30, "target": "foe"}],
    "Poison Jab":   [{"inflict": "poison",    "chance": 0.30, "target": "foe"}],
    "Gunk Shot":    [{"inflict": "poison",    "chance": 0.30, "target": "foe"}],
    "Sludge Wave":  [{"inflict": "poison",    "chance": 0.10, "target": "foe"}],
    "Psychic":      [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Psyshock":     [],
    "Shadow Ball":  [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.20}],
    "Crunch":       [{"stat": "def_",    "stages": -1, "target": "foe", "chance": 0.20}],
    "Earth Power":  [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Energy Ball":  [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Flash Cannon": [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Bug Buzz":     [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Moonblast":    [{"stat": "sp_atk",  "stages": -1, "target": "foe", "chance": 0.30}],
    "Play Rough":   [{"stat": "atk",     "stages": -1, "target": "foe", "chance": 0.10}],
    "Meteor Mash":  [{"stat": "atk",     "stages":  1, "target": "self","chance": 0.20}],
    "Mystical Fire":[{"stat": "sp_atk",  "stages": -1, "target": "foe", "chance": 1.00}],
    "Eerie Impulse":[{"stat": "sp_atk",  "stages": -2, "target": "foe", "chance": 1.00}],
    "Noble Roar":   [{"stat": "atk",     "stages": -1, "target": "foe", "chance": 1.00},
                     {"stat": "sp_atk",  "stages": -1, "target": "foe", "chance": 1.00}],
    "Parting Shot": [{"stat": "atk",     "stages": -1, "target": "foe", "chance": 1.00},
                     {"stat": "sp_atk",  "stages": -1, "target": "foe", "chance": 1.00}],
    # No-secondary moves (avoid PokéAPI deriving flinch/minor effects we don't implement)
    "Brave Bird":   [],
    "Wild Charge":  [],
    "Waterfall":    [],
    "Headbutt":     [],
    "Stomp":        [],
    "Bite":         [],
    # Hazards — engine doesn't implement entry hazards yet; include as empty secondaries
    "Stealth Rock": [],
    "Spikes":       [],
    "Toxic Spikes": [],
    "Sticky Web":   [],
}

SWITCH_AFTER_MOVES_API = {"u-turn", "volt-switch", "flip-turn"}

# Used in move pool scoring (api names, kebab-case)
USEFUL_STATUS_MOVES_API = {
    "toxic", "will-o-wisp", "thunder-wave", "glare", "stun-spore",
    "recover", "roost", "soft-boiled", "milk-drink", "moonlight", "morning-sun",
    "slack-off", "shore-up", "synthesis", "wish", "heal-order",
    "protect", "detect", "kings-shield", "spiky-shield", "baneful-bunker",
    "wide-guard", "quick-guard", "mat-block",
    "stealth-rock", "spikes", "toxic-spikes", "sticky-web",
    "swords-dance", "nasty-plot", "dragon-dance", "quiver-dance",
    "bulk-up", "calm-mind", "shell-smash", "agility", "rock-polish",
    "tail-glow", "geomancy", "shift-gear", "coil", "hone-claws", "work-up",
    "sleep-powder", "spore", "hypnosis", "dark-void", "sing", "lovely-kiss",
    "leech-seed", "substitute", "taunt", "encore",
    "u-turn", "volt-switch", "flip-turn", "parting-shot",
    "rapid-spin", "defog", "tailwind", "trick-room",
}

SETUP_MOVES_API = {
    "swords-dance", "nasty-plot", "dragon-dance", "quiver-dance",
    "bulk-up", "calm-mind", "shell-smash", "agility", "rock-polish",
    "coil", "hone-claws", "work-up", "tail-glow", "geomancy", "shift-gear",
}

RECOVERY_MOVES_API = {
    "recover", "roost", "soft-boiled", "milk-drink", "moonlight", "morning-sun",
    "slack-off", "shore-up", "synthesis", "wish", "heal-order",
}

PIVOT_MOVES_API = {"u-turn", "volt-switch", "flip-turn", "parting-shot"}

# PokéAPI priority field is authoritative; this supplements missing entries
PRIORITY_OVERRIDE: dict[str, int] = {
    "protect": 4, "detect": 4, "kings-shield": 4, "spiky-shield": 4,
    "baneful-bunker": 4, "wide-guard": 3, "quick-guard": 3, "mat-block": 3,
    "fake-out": 3, "feint": 2, "extreme-speed": 2, "first-impression": 2,
    "quick-attack": 1, "bullet-punch": 1, "mach-punch": 1, "sucker-punch": 1,
    "shadow-sneak": 1, "aqua-jet": 1, "ice-shard": 1, "vacuum-wave": 1,
    "trick-room": -7, "gyro-ball": 0, "avalanche": -4, "revenge": -4,
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "pokemon-battle-sim-research/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def api_name_to_display(api_name: str) -> str:
    """Convert PokéAPI kebab-case name to a human-readable display name."""
    if api_name in DISPLAY_NAME_EXCEPTIONS:
        return DISPLAY_NAME_EXCEPTIONS[api_name]
    return " ".join(word.capitalize() for word in api_name.split("-"))


# ---------------------------------------------------------------------------
# Phase 1 — Census (IDs 1–721, one fetch per Pokémon)
# ---------------------------------------------------------------------------

def fetch_single_census_entry(pokemon_id: int) -> dict | None:
    """Fetch name, types, base stats, and BST for one Pokémon by dex ID."""
    url = f"{POKEAPI_BASE}/pokemon/{pokemon_id}"
    try:
        raw = json.loads(fetch_url(url))
    except Exception as exc:
        print(f"  !! census fetch failed for ID {pokemon_id}: {exc}")
        return None

    base_stats: dict[str, int] = {}
    for stat_entry in raw["stats"]:
        json_key = POKEAPI_STAT_TO_JSON_KEY.get(stat_entry["stat"]["name"])
        if json_key:
            base_stats[json_key] = stat_entry["base_stat"]

    if len(base_stats) != 6:
        return None  # incomplete stat block — skip

    bst = sum(base_stats.values())
    types = [t["type"]["name"] for t in raw["types"]]

    return {
        "id": pokemon_id,
        "name": api_name_to_display(raw["name"]),
        "api_name": raw["name"],
        "types": types,
        "base_stats": base_stats,
        "bst": bst,
    }


def load_or_build_census(
    census_path: str,
    force: bool,
    max_id: int = 721,
    delay: float = REQUEST_DELAY,
) -> list[dict]:
    """Return census list, fetching from API only if cache is missing or --force."""
    if not force and os.path.exists(census_path):
        print(f"Loading existing census from {census_path}")
        with open(census_path) as f:
            return json.load(f)

    print(f"Fetching census for IDs 1–{max_id}...")
    entries: list[dict] = []
    for pokemon_id in range(1, max_id + 1):
        if pokemon_id % 50 == 0:
            print(f"  [{pokemon_id}/{max_id}] ...")
        entry = fetch_single_census_entry(pokemon_id)
        if entry is not None:
            entries.append(entry)
        time.sleep(delay)

    with open(census_path, "w") as f:
        json.dump(entries, f, indent=2)
    print(f"Census complete: {len(entries)} entries → {census_path}")
    return entries


# ---------------------------------------------------------------------------
# Phase 2 — Stratified pool selection
# ---------------------------------------------------------------------------

def _type_deficit_score(candidate_types: list[str], type_counts: dict[str, int]) -> int:
    """How many underrepresented types does this candidate fill?"""
    return sum(max(0, TARGET_PER_TYPE - type_counts.get(t, 0)) for t in candidate_types)


def select_stratified_pool(
    census_entries: list[dict],
    bst_bins: list[tuple[int, int, int]],
    rng: random.Random,
) -> list[dict]:
    """Greedily select ~170 Pokémon that cover all 18 types across BST bins."""
    type_counts: dict[str, int] = defaultdict(int)
    selected: list[dict] = []

    for bst_min, bst_max, target_count in bst_bins:
        bin_candidates = [
            p for p in census_entries
            if bst_min <= p["bst"] < bst_max
        ]
        rng.shuffle(bin_candidates)  # randomise within-tier tie-breaking
        picked: list[dict] = []

        while len(picked) < target_count and bin_candidates:
            # Pick the candidate that fills the most deficit types
            best_score = -1
            best_index = 0
            for idx, candidate in enumerate(bin_candidates):
                score = _type_deficit_score(candidate["types"], type_counts)
                if score > best_score:
                    best_score = score
                    best_index = idx
            chosen = bin_candidates.pop(best_index)
            picked.append(chosen)
            for t in chosen["types"]:
                type_counts[t] += 1

        selected.extend(picked)
        print(
            f"  BST {bst_min}–{bst_max}: picked {len(picked)}/{target_count} "
            f"(pool now {len(selected)})"
        )

    # Second pass: patch any type still below MIN_TYPE_COVERAGE
    underrepresented = [t for t in ALL_TYPES if type_counts[t] < MIN_TYPE_COVERAGE]
    if underrepresented:
        print(f"  Patching underrepresented types: {underrepresented}")
        selected_names = {p["name"] for p in selected}
        for missing_type in underrepresented:
            extras = [
                p for p in census_entries
                if missing_type in p["types"] and p["name"] not in selected_names
            ]
            if extras:
                extras.sort(key=lambda p: _type_deficit_score(p["types"], type_counts), reverse=True)
                chosen = extras[0]
                selected.append(chosen)
                selected_names.add(chosen["name"])
                for t in chosen["types"]:
                    type_counts[t] += 1
                print(f"    Added {chosen['name']} for {missing_type} coverage")

    print(f"\nStratified pool: {len(selected)} Pokémon")
    print("Type coverage:", {t: type_counts[t] for t in ALL_TYPES})
    return selected


# ---------------------------------------------------------------------------
# Phase 3/4 — Learnset fetch and move pool construction
# ---------------------------------------------------------------------------

def fetch_gen6_learnset(pokemon_api_name: str) -> list[str]:
    """Return list of move api_names learnable in Gen 6 (x-y or oras)."""
    url = f"{POKEAPI_BASE}/pokemon/{pokemon_api_name}"
    try:
        raw = json.loads(fetch_url(url))
    except Exception as exc:
        print(f"  !! learnset fetch failed for {pokemon_api_name!r}: {exc}")
        return []

    gen6_moves: list[str] = []
    for move_entry in raw["moves"]:
        for vg_detail in move_entry["version_group_details"]:
            if vg_detail["version_group"]["name"] in GEN6_VERSION_GROUPS:
                gen6_moves.append(move_entry["move"]["name"])
                break  # don't add the same move twice

    return gen6_moves


def fetch_raw_move(api_name: str) -> dict | None:
    """Fetch raw move data from PokéAPI."""
    url = f"{POKEAPI_BASE}/move/{api_name}"
    try:
        return json.loads(fetch_url(url))
    except Exception as exc:
        print(f"  !! move fetch failed for {api_name!r}: {exc}")
        return None


def load_move_cache(cache_path: str) -> dict[str, dict]:
    """Load previously fetched raw move data from cache file."""
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
    return {}


def save_move_cache(cache: dict[str, dict], cache_path: str) -> None:
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)


def ensure_move_cached(
    api_name: str,
    move_cache: dict[str, dict],
    cache_path: str,
    delay: float,
) -> dict | None:
    """Fetch and cache a move if not already present. Returns raw API data."""
    if api_name in move_cache:
        return move_cache[api_name]
    raw = fetch_raw_move(api_name)
    if raw is None:
        return None
    move_cache[api_name] = raw
    save_move_cache(move_cache, cache_path)
    time.sleep(delay)
    return raw


def derive_secondary_effects(display_name: str, api_name: str, raw_move: dict) -> list[dict]:
    """Derive secondary effect list in our format from PokéAPI move data.

    Uses SECONDARY_OVERRIDES for moves the API can't represent cleanly.
    All others are derived from ailment, stat_changes, and effect_chance fields.
    """
    if display_name in SECONDARY_OVERRIDES:
        return SECONDARY_OVERRIDES[display_name]

    effects: list[dict] = []
    is_status_move = raw_move["damage_class"]["name"] == "status"
    meta = raw_move.get("meta") or {}
    stat_changes = raw_move.get("stat_changes") or []

    ailment_name = (meta.get("ailment") or {}).get("name", "none")
    ailment_chance_pct = meta.get("ailment_chance") or 0
    stat_chance_pct = meta.get("stat_chance") or 0
    meta_category = (meta.get("category") or {}).get("name", "")

    # Status infliction
    if ailment_name != "none":
        internal_ailment = POKEAPI_AILMENT_TO_INTERNAL.get(ailment_name)
        if internal_ailment is not None:
            chance = ailment_chance_pct / 100.0 if ailment_chance_pct else 1.0
            effects.append({"inflict": internal_ailment, "chance": chance, "target": "foe"})

    # Stat changes
    for sc in stat_changes:
        api_stat_name = sc["stat"]["name"]
        effect_key = POKEAPI_STAT_TO_EFFECT_KEY.get(api_stat_name)
        if effect_key is None:
            continue
        stages = sc["change"]

        if is_status_move:
            target = "self"
            chance = 1.0
        else:
            if "lower" in meta_category:
                target = "foe"
            elif "raise" in meta_category:
                target = "self"
            else:
                # Infer: negative change on the attacker (self-lowering) vs lowering foe
                target = "self" if stages < 0 else "foe"
            chance = stat_chance_pct / 100.0 if stat_chance_pct else 1.0

        effects.append({"stat": effect_key, "stages": stages, "target": target, "chance": chance})

    return effects


def _base_move_score(api_name: str, pokemon_types: list[str], raw_move: dict) -> int:
    """Score a move for inclusion in the pool. Higher = higher priority."""
    power = raw_move.get("power")
    move_type = raw_move["type"]["name"]
    category = raw_move["damage_class"]["name"]
    is_stab = move_type in pokemon_types
    is_damaging = category != "status" and power is not None

    if is_stab and is_damaging and power >= 80:
        return 5
    if is_stab and is_damaging:
        return 4
    if not is_stab and is_damaging and power >= 70:
        return 3  # coverage — checked against already-covered types during selection
    if api_name in USEFUL_STATUS_MOVES_API:
        return 2
    return 1


def build_move_pool(
    gen6_learnset_api_names: list[str],
    pokemon_types: list[str],
    move_cache: dict[str, dict],
    rng: random.Random,
    min_pool_size: int = 6,
    max_pool_size: int = 8,
) -> list[str]:
    """Score and select the best moves from the Gen 6 learnset.

    Returns a list of api_names (up to max_pool_size, minimum min_pool_size).
    """
    available = [m for m in gen6_learnset_api_names if m in move_cache]
    if not available:
        return []

    scored = [
        (api_name, _base_move_score(api_name, pokemon_types, move_cache[api_name]))
        for api_name in available
    ]
    rng.shuffle(scored)                      # randomise ties before stable sort
    scored.sort(key=lambda x: -x[1])        # highest score first

    pool: list[str] = []
    covered_move_types: set[str] = set()

    for api_name, score in scored:
        if len(pool) >= max_pool_size:
            break
        raw = move_cache[api_name]
        move_type = raw["type"]["name"]

        # Skip score-3 coverage moves whose type is already in the pool
        if score == 3 and move_type in covered_move_types:
            continue

        pool.append(api_name)
        if raw["damage_class"]["name"] != "status" and raw.get("power"):
            covered_move_types.add(move_type)

    # Pad to minimum with score-1 moves if needed
    if len(pool) < min_pool_size:
        remaining = [api_name for api_name, _ in scored if api_name not in pool]
        pool.extend(remaining[: min_pool_size - len(pool)])

    return pool[:max_pool_size]


# ---------------------------------------------------------------------------
# Phase 5 — Archetype derivation
# ---------------------------------------------------------------------------

def derive_archetype(
    base_stats: dict[str, int],
    gen6_learnset_api_names: list[str],
) -> str:
    """Assign a behavioral archetype from base stats and learnset."""
    hp      = base_stats["hp"]
    atk     = base_stats["atk"]
    def_    = base_stats["def"]
    sp_atk  = base_stats["sp_atk"]
    sp_def  = base_stats["sp_def"]
    spe     = base_stats["spe"]

    bulk_score = hp * (def_ + sp_def) / 250
    offense    = max(atk, sp_atk)
    learnset   = set(gen6_learnset_api_names)

    has_recovery = bool(learnset & RECOVERY_MOVES_API)
    has_setup    = bool(learnset & SETUP_MOVES_API)
    has_pivot    = bool(learnset & PIVOT_MOVES_API)

    if bulk_score > 18000 and has_recovery:
        return "wall"
    if offense >= 120 and min(def_, sp_def) < 60:
        return "glass_cannon"
    if has_setup and offense >= 85:
        return "setup_sweeper"
    if spe >= 100 and offense >= 100:
        return "sweeper"
    if has_pivot:
        return "pivot"
    if bulk_score > 15000:
        return "tank"
    if spe >= 90 and offense >= 95:
        return "fast_attacker"
    return "tank"


# ---------------------------------------------------------------------------
# Output entry builders
# ---------------------------------------------------------------------------

def build_pokemon_entry(
    census_entry: dict,
    gen6_learnset_api_names: list[str],
    move_pool_api_names: list[str],
) -> dict:
    """Build the final pokemon.json entry for one Pokémon."""
    base = census_entry["base_stats"]
    archetype = derive_archetype(base, gen6_learnset_api_names)
    move_pool_display = [api_name_to_display(m) for m in move_pool_api_names]

    return {
        "name":     census_entry["name"],
        "types":    census_entry["types"],
        "hp":       base["hp"],
        "atk":      base["atk"],
        "def":      base["def"],
        "sp_atk":   base["sp_atk"],
        "sp_def":   base["sp_def"],
        "spe":      base["spe"],
        "bst":      census_entry["bst"],
        "archetype": archetype,
        "move_pool": move_pool_display,
    }


def build_move_entry(display_name: str, api_name: str, raw_move: dict) -> dict:
    """Build a moves.json entry from raw PokéAPI move data."""
    secondary = derive_secondary_effects(display_name, api_name, raw_move)
    contact = raw_move["damage_class"]["name"] == "physical"
    priority = raw_move.get("priority") or PRIORITY_OVERRIDE.get(api_name, 0)
    switch_after = api_name in SWITCH_AFTER_MOVES_API

    entry: dict = {
        "name":      display_name,
        "type":      raw_move["type"]["name"],
        "power":     raw_move.get("power"),
        "accuracy":  raw_move.get("accuracy"),
        "category":  raw_move["damage_class"]["name"],
        "contact":   contact,
        "priority":  priority,
        "secondary": secondary,
    }
    if switch_after:
        entry["switch_after"] = True
    return entry


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-fetch everything, ignoring caches")
    parser.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for stratified sampling")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    census_path    = os.path.join(out_dir, "pokemon_census.json")
    move_cache_path = os.path.join(out_dir, "moves_cache.json")
    pokemon_path   = os.path.join(out_dir, "pokemon.json")
    moves_path     = os.path.join(out_dir, "moves.json")

    rng = random.Random(args.seed)

    # ---- Phase 1: Census ----
    census = load_or_build_census(census_path, force=args.force)
    viable_census = [p for p in census if p["bst"] >= 300]
    print(f"\nViable census entries (BST ≥ 300): {len(viable_census)}")

    # ---- Phase 2: Stratified selection ----
    print("\nSelecting stratified pool...")
    selected_pool = select_stratified_pool(viable_census, BST_BINS, rng)

    # ---- Load existing output (for resumability) ----
    existing_pokemon: list[dict] = []
    if not args.force and os.path.exists(pokemon_path):
        with open(pokemon_path) as f:
            existing_pokemon = json.load(f)
        print(f"\nFound {len(existing_pokemon)} existing entries in {pokemon_path}")

    existing_names = {p["name"] for p in existing_pokemon}
    to_fetch = [p for p in selected_pool if p["name"] not in existing_names]
    print(f"Need to fetch learnsets for {len(to_fetch)} Pokémon")

    # ---- Load move cache ----
    move_cache = load_move_cache(move_cache_path)
    print(f"Move cache: {len(move_cache)} moves already cached")

    # ---- Phase 3/4: Learnset + move pool per Pokémon ----
    new_pokemon_entries: list[dict] = []
    all_move_pool_api_names: set[str] = set()

    # Collect api_names from existing entries too
    existing_moves_json: list[dict] = []
    if os.path.exists(moves_path):
        with open(moves_path) as f:
            existing_moves_json = json.load(f)
    existing_move_display_names = {m["name"] for m in existing_moves_json}

    # Display names → api_names reverse map for existing pool moves
    display_to_api: dict[str, str] = {}
    for entry in existing_pokemon:
        for display_name in entry.get("move_pool", []):
            api_n = display_name.lower().replace(" ", "-").replace("'", "")
            display_to_api[display_name] = api_n
            all_move_pool_api_names.add(api_n)

    for idx, census_entry in enumerate(to_fetch):
        poke_name = census_entry["name"]
        poke_api_name = census_entry["api_name"]
        print(f"\n[{idx + 1}/{len(to_fetch)}] {poke_name} (BST {census_entry['bst']}, {census_entry['types']})")

        # Fetch Gen 6 learnset
        gen6_learnset = fetch_gen6_learnset(poke_api_name)
        time.sleep(REQUEST_DELAY)
        print(f"  Gen 6 learnset: {len(gen6_learnset)} moves")

        if not gen6_learnset:
            print(f"  !! No Gen 6 learnset found — skipping {poke_name}")
            continue

        # Fetch any uncached move data from the learnset
        uncached = [m for m in gen6_learnset if m not in move_cache]
        if uncached:
            print(f"  Fetching {len(uncached)} uncached moves...")
        for move_api_name in uncached:
            ensure_move_cached(move_api_name, move_cache, move_cache_path, REQUEST_DELAY)

        # Build scored move pool
        pool_api_names = build_move_pool(
            gen6_learnset, census_entry["types"], move_cache, rng
        )
        if len(pool_api_names) < 6:
            print(f"  !! WARNING: only {len(pool_api_names)} moves in pool for {poke_name}")

        all_move_pool_api_names.update(pool_api_names)

        poke_entry = build_pokemon_entry(census_entry, gen6_learnset, pool_api_names)
        new_pokemon_entries.append(poke_entry)
        print(f"  archetype={poke_entry['archetype']}, pool={poke_entry['move_pool']}")

    # ---- Write pokemon.json ----
    combined_pokemon = existing_pokemon + new_pokemon_entries
    with open(pokemon_path, "w") as f:
        json.dump(combined_pokemon, f, indent=2)
    print(f"\nWrote {len(combined_pokemon)} Pokémon → {pokemon_path}")

    # ---- Rebuild moves.json from all pool moves ----
    print(f"\nBuilding moves.json for {len(all_move_pool_api_names)} pool moves...")
    move_entries: list[dict] = []
    for move_api_name in sorted(all_move_pool_api_names):
        raw = move_cache.get(move_api_name)
        if raw is None:
            raw = fetch_raw_move(move_api_name)
            if raw is None:
                print(f"  !! Could not fetch move data for {move_api_name!r} — skipping")
                continue
            move_cache[move_api_name] = raw
            time.sleep(REQUEST_DELAY)
        display = api_name_to_display(move_api_name)
        move_entries.append(build_move_entry(display, move_api_name, raw))

    with open(moves_path, "w") as f:
        json.dump(move_entries, f, indent=2)
    print(f"Wrote {len(move_entries)} moves → {moves_path}")

    print("\nDone. Commit data/ to repo.")


if __name__ == "__main__":
    main()

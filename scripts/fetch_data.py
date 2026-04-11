"""
One-time data fetch: Smogon usage stats + PokéAPI base stats → data/pokemon.json + data/moves.json

Pulls top N Pokémon from Gen 6 NU (1760+ rating) and their competitive sets.
Run once; commit the output files. Never call this at battle runtime.

Usage:
    python scripts/fetch_data.py [--tier gen6nu] [--rating 1760] [--top 35] [--month 2026-03]
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SMOGON_BASE = "https://www.smogon.com/stats"
POKEAPI_BASE = "https://pokeapi.co/api/v2"

# Items we know how to handle — map Smogon name → our item name
KNOWN_ITEMS = {
    "Choice Scarf", "Choice Band", "Choice Specs",
    "Leftovers", "Life Orb", "Rocky Helmet",
    "Lum Berry", "Black Sludge", "Assault Vest",
    "Sitrus Berry", "Focus Sash", "Expert Belt", "Eviolite",
}

# Moves with secondary effects we support, by name → secondary list
# Anything not here gets an empty secondary list (move still deals damage/status)
KNOWN_SECONDARIES = {
    "Flamethrower":  [{"inflict": "burn",      "chance": 0.10, "target": "foe"}],
    "Fire Blast":    [{"inflict": "burn",      "chance": 0.10, "target": "foe"}],
    "Flare Blitz":   [{"inflict": "burn",      "chance": 0.10, "target": "self"}],
    "Brave Bird":    [{"inflict": "burn",      "chance": 0.10, "target": "self"}],
    "Wild Charge":   [{"inflict": "burn",      "chance": 0.10, "target": "self"}],
    "Scald":         [{"inflict": "burn",      "chance": 0.30, "target": "foe"}],
    "Will-O-Wisp":   [{"inflict": "burn",      "chance": 1.00, "target": "foe"}],
    "Thunderbolt":   [{"inflict": "paralysis", "chance": 0.10, "target": "foe"}],
    "Thunder":       [{"inflict": "paralysis", "chance": 0.30, "target": "foe"}],
    "Thunder Wave":  [{"inflict": "paralysis", "chance": 1.00, "target": "foe"}],
    "Body Slam":     [{"inflict": "paralysis", "chance": 0.30, "target": "foe"}],
    "Waterfall":     [{"inflict": "paralysis", "chance": 0.20, "target": "foe"}],
    "Ice Beam":      [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Ice Fang":      [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Blizzard":      [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Icicle Crash":  [{"inflict": "freeze",    "chance": 0.10, "target": "foe"}],
    "Sludge Bomb":   [{"inflict": "poison",    "chance": 0.30, "target": "foe"}],
    "Poison Jab":    [{"inflict": "poison",    "chance": 0.30, "target": "foe"}],
    "Toxic":         [{"inflict": "badly_poison", "chance": 1.00, "target": "foe"}],
    "Hypnosis":      [{"inflict": "sleep",     "chance": 1.00, "target": "foe"}],
    "Sleep Powder":  [{"inflict": "sleep",     "chance": 1.00, "target": "foe"}],
    "Spore":         [{"inflict": "sleep",     "chance": 1.00, "target": "foe"}],
    "Psychic":       [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Psyshock":      [],
    "Shadow Ball":   [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.20}],
    "Crunch":        [{"stat": "def_",    "stages": -1, "target": "foe", "chance": 0.20}],
    "Earth Power":   [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Energy Ball":   [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Flash Cannon":  [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Bug Buzz":      [{"stat": "sp_def",  "stages": -1, "target": "foe", "chance": 0.10}],
    "Moonblast":     [{"stat": "sp_atk",  "stages": -1, "target": "foe", "chance": 0.30}],
    "Play Rough":    [{"stat": "atk",     "stages": -1, "target": "foe", "chance": 0.10}],
    "Close Combat":  [{"stat": "def_",    "stages": -1, "target": "self", "chance": 1.00},
                      {"stat": "sp_def",  "stages": -1, "target": "self", "chance": 1.00}],
    "Leaf Storm":    [{"stat": "sp_atk",  "stages": -2, "target": "self", "chance": 1.00}],
    "Draco Meteor":  [{"stat": "sp_atk",  "stages": -2, "target": "self", "chance": 1.00}],
    "Meteor Mash":   [{"stat": "atk",     "stages": 1,  "target": "self", "chance": 0.20}],
    "Dragon Dance":  [{"stat": "atk",     "stages": 1,  "target": "self", "chance": 1.00},
                      {"stat": "spe",     "stages": 1,  "target": "self", "chance": 1.00}],
    "Calm Mind":     [{"stat": "sp_atk",  "stages": 1,  "target": "self", "chance": 1.00},
                      {"stat": "sp_def",  "stages": 1,  "target": "self", "chance": 1.00}],
    "Bulk Up":       [{"stat": "atk",     "stages": 1,  "target": "self", "chance": 1.00},
                      {"stat": "def_",    "stages": 1,  "target": "self", "chance": 1.00}],
    "Swords Dance":  [{"stat": "atk",     "stages": 2,  "target": "self", "chance": 1.00}],
    "Nasty Plot":    [{"stat": "sp_atk",  "stages": 2,  "target": "self", "chance": 1.00}],
    "Quiver Dance":  [{"stat": "sp_atk",  "stages": 1,  "target": "self", "chance": 1.00},
                      {"stat": "sp_def",  "stages": 1,  "target": "self", "chance": 1.00},
                      {"stat": "spe",     "stages": 1,  "target": "self", "chance": 1.00}],
    "Shell Smash":   [{"stat": "atk",     "stages": 2,  "target": "self", "chance": 1.00},
                      {"stat": "sp_atk",  "stages": 2,  "target": "self", "chance": 1.00},
                      {"stat": "spe",     "stages": 2,  "target": "self", "chance": 1.00},
                      {"stat": "def_",    "stages": -1, "target": "self", "chance": 1.00},
                      {"stat": "sp_def",  "stages": -1, "target": "self", "chance": 1.00}],
    "Recover":       [{"heal_fraction": 0.5, "target": "self", "chance": 1.00}],
    "Roost":         [{"heal_fraction": 0.5, "target": "self", "chance": 1.00}],
    "Moonlight":     [{"heal_fraction": 0.5, "target": "self", "chance": 1.00}],
    "Slack Off":     [{"heal_fraction": 0.5, "target": "self", "chance": 1.00}],
    "Soft-Boiled":   [{"heal_fraction": 0.5, "target": "self", "chance": 1.00}],
    "Milk Drink":    [{"heal_fraction": 0.5, "target": "self", "chance": 1.00}],
    "Morning Sun":   [{"heal_fraction": 0.5, "target": "self", "chance": 1.00}],
    "Protect":       [{"protect": True, "target": "self", "chance": 1.00}],
    "U-turn":        [],  # switch_after handled separately
    "Volt Switch":   [],
}

SWITCH_AFTER_MOVES = {"U-turn", "Volt Switch"}

PRIORITY_MOVES = {
    "ExtremeSpeed": 2, "Extreme Speed": 2,
    "Quick Attack": 1, "Bullet Punch": 1, "Mach Punch": 1,
    "Sucker Punch": 1, "Shadow Sneak": 1, "Aqua Jet": 1,
    "Protect": 4, "Detect": 4,
}

# PokéAPI stat name → our field name
STAT_MAP = {
    "hp": "hp", "attack": "atk", "defense": "def",
    "special-attack": "sp_atk", "special-defense": "sp_def", "speed": "spe",
}

# Assign archetype based on stat profile heuristics
def _archetype(base_stats: dict, moves: list[str]) -> str:
    hp, atk, def_, sp_atk, sp_def, spe = (
        base_stats["hp"], base_stats["atk"], base_stats["def"],
        base_stats["sp_atk"], base_stats["sp_def"], base_stats["spe"],
    )
    bulk = (hp * (def_ + sp_def)) / 250
    offense = max(atk, sp_atk)
    has_recovery = any(m in KNOWN_SECONDARIES and
                       any("heal_fraction" in e for e in KNOWN_SECONDARIES[m])
                       for m in moves)
    has_setup = any(m in ("Dragon Dance", "Swords Dance", "Nasty Plot", "Calm Mind",
                           "Quiver Dance", "Shell Smash", "Bulk Up") for m in moves)
    if bulk > 18000 and has_recovery:
        return "wall"
    if spe >= 100 and offense >= 100 and not has_recovery:
        return "glass_cannon"
    if spe >= 85 and has_setup:
        return "setup_sweeper"
    if has_setup and offense >= 90:
        return "setup_sweeper"
    if "U-turn" in moves or "Volt Switch" in moves:
        return "pivot"
    if spe >= 85 and offense >= 100:
        return "fast_attacker"
    if bulk > 15000:
        return "tank"
    return "tank"


def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "pokemon-battle-sim-research/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def parse_usage(text: str) -> list[tuple[str, float]]:
    """Return [(name, usage_pct), ...] sorted by rank."""
    results = []
    for line in text.splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*([\w\- ]+?)\s*\|\s*([\d.]+)%", line)
        if m:
            name = m.group(1).strip()
            pct = float(m.group(2))
            results.append((name, pct))
    return results


def parse_moveset(text: str) -> dict[str, dict]:
    """Parse moveset file → {name: {items, spreads, moves, raw_count}}."""
    entries = {}
    current = None
    section = None

    for line in text.splitlines():
        line = line.strip("| \n")
        if re.match(r"\+[-]+\+", line.strip("|").strip()):
            continue
        if not line:
            continue

        # New Pokémon block starts with just the name on a line by itself (no numbers)
        if re.match(r"^[A-Z][A-Za-z0-9\-\' ]+$", line) and "%" not in line and ":" not in line:
            # Check it's a Pokémon name (not a section header like "Abilities")
            if line not in ("Abilities", "Items", "Spreads", "Moves", "Teammates"):
                current = line
                entries[current] = {"items": [], "spreads": [], "moves": [], "raw_count": 0}
                section = None
                continue

        if current is None:
            continue

        if line.startswith("Raw count:"):
            entries[current]["raw_count"] = int(line.split(":")[1].strip())
            continue

        if line in ("Abilities", "Items", "Spreads", "Moves", "Teammates"):
            section = line.lower()
            continue

        if section and "%" in line:
            m = re.match(r"(.+?)\s+([\d.]+)%", line)
            if m:
                entry_name = m.group(1).strip()
                pct = float(m.group(2))
                if entry_name == "Other":
                    continue
                if section == "items":
                    entries[current]["items"].append((entry_name, pct))
                elif section == "spreads":
                    entries[current]["spreads"].append((entry_name, pct))
                elif section == "moves":
                    entries[current]["moves"].append((entry_name, pct))

    return entries


def fetch_pokemon_data(name: str) -> dict | None:
    """Fetch base stats + types from PokéAPI."""
    api_name = name.lower().replace(" ", "-").replace("'", "")
    # Handle common form names
    api_name = re.sub(r"-mega$", "-mega", api_name)
    url = f"{POKEAPI_BASE}/pokemon/{api_name}"
    try:
        raw = json.loads(fetch_url(url))
    except Exception as e:
        print(f"  !! PokéAPI failed for {name!r} ({api_name}): {e}")
        return None

    stats = {}
    for s in raw["stats"]:
        key = STAT_MAP.get(s["stat"]["name"])
        if key:
            stats[key] = s["base_stat"]

    types = [t["type"]["name"] for t in raw["types"]]
    return {"base_stats": stats, "types": types}


def fetch_move_data(name: str) -> dict | None:
    """Fetch move metadata from PokéAPI."""
    api_name = name.lower().replace(" ", "-").replace("'", "").replace(".", "")
    url = f"{POKEAPI_BASE}/move/{api_name}"
    try:
        raw = json.loads(fetch_url(url))
    except Exception as e:
        print(f"  !! PokéAPI move failed for {name!r}: {e}")
        return None

    category = raw["damage_class"]["name"]  # "physical", "special", "status"
    move_type = raw["type"]["name"]
    power = raw.get("power")
    accuracy = raw.get("accuracy")
    return {
        "name": name,
        "type": move_type,
        "power": power,
        "accuracy": accuracy,
        "category": category,
    }


def pick_item(items: list[tuple]) -> str | None:
    for name, _ in items:
        if name in KNOWN_ITEMS:
            return name
    return None


def pick_spread(spreads: list[tuple]) -> tuple[str, dict]:
    """Return (nature, evs_dict) from top spread."""
    if not spreads:
        return "Hardy", {}
    top = spreads[0][0]  # e.g. "Timid:0/0/0/252/4/252"
    nature, ev_str = top.split(":")
    ev_vals = [int(x) for x in ev_str.split("/")]
    keys = ["hp", "atk", "def", "sp_atk", "sp_def", "spe"]
    evs = {k: v for k, v in zip(keys, ev_vals) if v > 0}
    return nature, evs


def build_pokemon_entry(
    name: str,
    usage_pct: float,
    poke_data: dict,
    moveset: dict,
) -> dict:
    base = poke_data["base_stats"]
    types = poke_data["types"]
    item = pick_item(moveset.get("items", []))
    nature, evs = pick_spread(moveset.get("spreads", []))
    move_names = [m for m, _ in moveset.get("moves", [])][:4]
    archetype = _archetype(base, move_names)

    return {
        "name": name,
        "types": types,
        "hp": base["hp"],
        "atk": base["atk"],
        "def": base["def"],
        "sp_atk": base["sp_atk"],
        "sp_def": base["sp_def"],
        "spe": base["spe"],
        "nature": nature,
        "evs": evs,
        "moves": move_names,
        "held_item": item,
        "usage_pct": round(usage_pct, 3),
        "archetype": archetype,
    }


def build_move_entry(name: str, api_data: dict) -> dict:
    secondary = KNOWN_SECONDARIES.get(name, [])
    contact = api_data["category"] == "physical"
    priority = PRIORITY_MOVES.get(name, 0)
    switch_after = name in SWITCH_AFTER_MOVES

    entry = {
        "name": name,
        "type": api_data["type"],
        "power": api_data["power"],
        "accuracy": api_data["accuracy"],
        "category": api_data["category"],
        "contact": contact,
        "priority": priority,
        "secondary": secondary,
    }
    if switch_after:
        entry["switch_after"] = True
    return entry


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tier", default="gen6nu")
    p.add_argument("--rating", default="1760")
    p.add_argument("--top", type=int, default=35)
    p.add_argument("--month", default="2026-03")
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    args = p.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    tier_key = f"{args.tier}-{args.rating}"

    print(f"Fetching {tier_key} stats for {args.month}, top {args.top} Pokémon...\n")

    # 1. Usage list
    usage_url = f"{SMOGON_BASE}/{args.month}/{tier_key}.txt"
    print(f"Usage: {usage_url}")
    usage_text = fetch_url(usage_url)
    usage_list = parse_usage(usage_text)[: args.top]
    print(f"  Got {len(usage_list)} entries: {[n for n, _ in usage_list[:5]]}...")

    # 2. Moveset file
    moveset_url = f"{SMOGON_BASE}/{args.month}/moveset/{tier_key}.txt"
    print(f"Moveset: {moveset_url}")
    moveset_text = fetch_url(moveset_url)
    movesets = parse_moveset(moveset_text)
    print(f"  Parsed {len(movesets)} moveset entries")

    # 3. Build Pokémon + collect unique moves
    pokemon_entries = []
    all_move_names: set[str] = set()

    print(f"\nFetching PokéAPI data for {len(usage_list)} Pokémon...")
    for name, usage_pct in usage_list:
        print(f"  {name} ({usage_pct:.1f}%)")
        poke_data = fetch_pokemon_data(name)
        if poke_data is None:
            print(f"    skipped (PokéAPI miss)")
            continue
        ms = movesets.get(name, {})
        entry = build_pokemon_entry(name, usage_pct, poke_data, ms)
        pokemon_entries.append(entry)
        all_move_names.update(entry["moves"])
        time.sleep(0.3)  # be polite to PokéAPI

    print(f"\nFetching PokéAPI data for {len(all_move_names)} unique moves...")
    move_entries = []
    seen_moves = set()
    for move_name in sorted(all_move_names):
        if move_name in seen_moves:
            continue
        seen_moves.add(move_name)
        print(f"  {move_name}")
        api_data = fetch_move_data(move_name)
        if api_data is None:
            # Stub: unknown move
            move_entries.append({
                "name": move_name, "type": "normal", "power": None,
                "accuracy": None, "category": "status",
                "contact": False, "priority": 0, "secondary": [],
            })
        else:
            move_entries.append(build_move_entry(move_name, api_data))
        time.sleep(0.2)

    # 4. Write output
    poke_path = os.path.join(out_dir, "pokemon.json")
    moves_path = os.path.join(out_dir, "moves.json")

    with open(poke_path, "w") as f:
        json.dump(pokemon_entries, f, indent=2)
    with open(moves_path, "w") as f:
        json.dump(move_entries, f, indent=2)

    print(f"\nWrote {len(pokemon_entries)} Pokémon → {poke_path}")
    print(f"Wrote {len(move_entries)} moves → {moves_path}")
    print("\nDone. Commit data/ to repo.")


if __name__ == "__main__":
    main()

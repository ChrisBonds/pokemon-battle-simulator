"""6v6 smoke test — verifies the expanded battle system end-to-end."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.move import Move
from simulator.pokemon import Pokemon
from simulator.trainer import Trainer
from simulator.battle import Battle

# ------------------------------------------------------------------
# Move definitions
# ------------------------------------------------------------------

# Physical
tackle      = Move("Tackle",        "normal",   40,  100, "physical")
flare_blitz = Move("Flare Blitz",   "fire",     120, 100, "physical", secondary=[{"inflict": "burn", "chance": 0.1, "target": "self"}])
waterfall   = Move("Waterfall",     "water",    80,  100, "physical", secondary=[{"inflict": "paralysis", "chance": 0.2, "target": "foe"}])
earthquake  = Move("Earthquake",    "ground",   100, 100, "physical")
close_combat= Move("Close Combat",  "fighting", 120, 100, "physical", secondary=[{"stat": "def_",   "stages": -1, "target": "self", "chance": 1.0}, {"stat": "sp_def", "stages": -1, "target": "self", "chance": 1.0}])
dragon_claw = Move("Dragon Claw",   "dragon",   80,  100, "physical")
x_scissor   = Move("X-Scissor",     "bug",      80,  100, "physical")
extreme_spd = Move("ExtremeSpeed",  "normal",   80,  100, "physical", priority=2)
ice_fang    = Move("Ice Fang",      "ice",      65,  95,  "physical", secondary=[{"inflict": "freeze", "chance": 0.1, "target": "foe"}])
crunch      = Move("Crunch",        "dark",     80,  100, "physical", secondary=[{"stat": "def_",   "stages": -1, "target": "foe", "chance": 0.2}])
cross_chop  = Move("Cross Chop",    "fighting", 100, 80,  "physical")
rock_blast  = Move("Rock Blast",    "rock",     75,  90,  "physical")

# Special
flamethrower= Move("Flamethrower",  "fire",     90,  100, "special", contact=False, secondary=[{"inflict": "burn",      "chance": 0.1, "target": "foe"}])
surf        = Move("Surf",          "water",    90,  100, "special", contact=False)
ice_beam    = Move("Ice Beam",      "ice",      90,  100, "special", contact=False, secondary=[{"inflict": "freeze",    "chance": 0.1, "target": "foe"}])
thunderbolt = Move("Thunderbolt",   "electric", 90,  100, "special", contact=False, secondary=[{"inflict": "paralysis", "chance": 0.1, "target": "foe"}])
psychic_m   = Move("Psychic",       "psychic",  90,  100, "special", contact=False, secondary=[{"stat": "sp_def",       "stages": -1, "target": "foe", "chance": 0.1}])
shadow_ball = Move("Shadow Ball",   "ghost",    80,  100, "special", contact=False, secondary=[{"stat": "sp_def",       "stages": -1, "target": "foe", "chance": 0.2}])
sludge_bomb = Move("Sludge Bomb",   "poison",   90,  100, "special", contact=False, secondary=[{"inflict": "poison",    "chance": 0.3, "target": "foe"}])
leaf_storm  = Move("Leaf Storm",    "grass",    130, 90,  "special", contact=False, secondary=[{"stat": "sp_atk",       "stages": -2, "target": "self", "chance": 1.0}])
draco_meteor= Move("Draco Meteor",  "dragon",   130, 90,  "special", contact=False, secondary=[{"stat": "sp_atk",       "stages": -2, "target": "self", "chance": 1.0}])
focus_blast = Move("Focus Blast",   "fighting", 120, 70,  "special", contact=False)
blizzard    = Move("Blizzard",      "ice",      110, 70,  "special", contact=False, secondary=[{"inflict": "freeze",    "chance": 0.1, "target": "foe"}])

# Status
dragon_dance= Move("Dragon Dance",  "dragon",   None, None, "status", secondary=[{"stat": "atk", "stages": 1, "target": "self", "chance": 1.0}, {"stat": "spe", "stages": 1, "target": "self", "chance": 1.0}])
calm_mind   = Move("Calm Mind",     "psychic",  None, None, "status", secondary=[{"stat": "sp_atk", "stages": 1, "target": "self", "chance": 1.0}, {"stat": "sp_def", "stages": 1, "target": "self", "chance": 1.0}])
bulk_up     = Move("Bulk Up",       "fighting", None, None, "status", secondary=[{"stat": "atk", "stages": 1, "target": "self", "chance": 1.0}, {"stat": "def_", "stages": 1, "target": "self", "chance": 1.0}])
thunder_wave= Move("Thunder Wave",  "electric", None, None, "status", secondary=[{"inflict": "paralysis", "chance": 1.0, "target": "foe"}])
hypnosis    = Move("Hypnosis",      "psychic",  None, 60,  "status", secondary=[{"inflict": "sleep", "chance": 1.0, "target": "foe"}])

# ------------------------------------------------------------------
# Team definitions  (stats are real base stats, level 50)
# ------------------------------------------------------------------

def make_team_ash():
    return [
        Pokemon("Charizard",  ["fire", "flying"],  78,  84,  78, 109,  85, 100, [flamethrower, dragon_claw, flare_blitz, dragon_dance], held_item="Life Orb"),
        Pokemon("Blastoise",  ["water"],            79,  83, 100,  85, 105,  78, [surf, ice_beam, thunderbolt, tackle],                   held_item="Leftovers"),
        Pokemon("Venusaur",   ["grass", "poison"],  80,  82,  83, 100, 100,  80, [leaf_storm, sludge_bomb, thunder_wave, tackle],         held_item="Black Sludge"),
        Pokemon("Gengar",     ["ghost", "poison"],  60,  65,  60, 130,  75, 110, [shadow_ball, sludge_bomb, focus_blast, hypnosis]),
        Pokemon("Dragonite",  ["dragon", "flying"], 91, 134,  95, 100, 100,  80, [dragon_claw, extreme_spd, draco_meteor, dragon_dance],  held_item="Choice Band"),
        Pokemon("Pikachu",    ["electric"],         35,  55,  40,  50,  50,  90, [thunderbolt, surf, thunder_wave, tackle]),
    ]


def make_team_gary():
    return [
        Pokemon("Arcanine",   ["fire"],             90, 110,  80, 100,  80,  95, [flare_blitz, extreme_spd, crunch, tackle],              held_item="Choice Scarf"),
        Pokemon("Gyarados",   ["water", "flying"],  95, 125,  79,  60, 100,  81, [waterfall, crunch, ice_fang, dragon_dance],             held_item="Lum Berry"),
        Pokemon("Alakazam",   ["psychic"],          55,  50,  45, 135,  95, 120, [psychic_m, shadow_ball, focus_blast, calm_mind],        held_item="Choice Specs"),
        Pokemon("Machamp",    ["fighting"],         90, 130,  80,  65,  85,  55, [close_combat, cross_chop, bulk_up, earthquake]),
        Pokemon("Rhydon",     ["ground", "rock"],  105, 130, 120,  45,  45,  40, [earthquake, rock_blast, crunch, tackle],                held_item="Rocky Helmet"),
        Pokemon("Lapras",     ["water", "ice"],    130,  85,  80,  85,  95,  60, [surf, blizzard, thunderbolt, ice_beam]),
    ]


# ------------------------------------------------------------------
# Run matchups
# ------------------------------------------------------------------

def run_series(name1: str, s1: str, name2: str, s2: str, n: int = 20) -> None:
    wins = {name1: 0, name2: 0}
    total_turns = 0

    for _ in range(n):
        t1 = Trainer(name1, make_team_ash(), strategy=s1)
        t2 = Trainer(name2, make_team_gary(), strategy=s2)
        result = Battle(t1, t2, verbose=False).run()
        wins[result.winner.name] += 1
        total_turns += result.turns

    print(f"\n{name1} ({s1}) vs {name2} ({s2})  —  {n} battles")
    print(f"  {name1}: {wins[name1]} wins  |  {name2}: {wins[name2]} wins")
    print(f"  Avg turns: {total_turns / n:.1f}")


if __name__ == "__main__":
    print("Running 6v6 smoke test...\n")

    # Single verbose battle first so we can eyeball the log
    t1 = Trainer("Ash",  make_team_ash(),  strategy="greedy")
    t2 = Trainer("Gary", make_team_gary(), strategy="greedy")
    result = Battle(t1, t2, verbose=True).run()
    print(f"\n{result}\n")

    # Strategy comparison series
    run_series("Ash", "random",  "Gary", "greedy",  n=30)
    run_series("Ash", "greedy",  "Gary", "minimax", n=30)
    run_series("Ash", "minimax", "Gary", "random",  n=30)

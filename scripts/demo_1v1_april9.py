"""Quick smoke test — verifies move/pokemon/trainer/battle wiring end-to-end."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator.move import Move
from simulator.pokemon import Pokemon
from simulator.trainer import Trainer
from simulator.battle import Battle

flamethrower = Move("Flamethrower", "fire", 90, 100, "special")
surf = Move("Surf", "water", 90, 100, "special")

charizard = Pokemon("Charizard", ["fire", "flying"], 78, 84, 78, 109, 85, 100, [flamethrower])
blastoise = Pokemon("Blastoise", ["water"], 79, 83, 100, 85, 105, 78, [surf])

t1 = Trainer("Ash", [charizard], strategy="greedy")
t2 = Trainer("Chris", [blastoise], strategy="greedy")

result = Battle(t1, t2).run()
print(result)

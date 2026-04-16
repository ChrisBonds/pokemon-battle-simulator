"""Evolutionary tournament infrastructure for genome-parameterised agents."""

from __future__ import annotations

import copy
import random
import statistics
from dataclasses import dataclass, field

from simulator.battle import Battle
from simulator.genome import FamilyType, Genome, mutate, random_genome
from simulator.pokemon import Pokemon
from simulator.team_builder import build_team, FAMILY_ARCHETYPE
from simulator.trainer import Trainer


@dataclass
class Agent:
    """An evolvable participant — wraps a Trainer blueprint with fitness tracking."""

    trainer_name: str
    family: FamilyType
    genome: Genome
    initial_bag: dict[str, int] = field(default_factory=dict)
    wins: int = 0
    losses: int = 0

    @property
    def fitness(self) -> float:
        """Win rate over all games played this generation; 0.0 if no games."""
        total_games = self.wins + self.losses
        return self.wins / total_games if total_games > 0 else 0.0

    def reset_record(self) -> None:
        """Clear wins/losses at the start of each generation."""
        self.wins = 0
        self.losses = 0


@dataclass
class GenerationSnapshot:
    """Summary statistics recorded at the end of each generation."""

    generation: int
    family_win_rates: dict[str, float]       # FamilyType.value → mean win rate
    mean_genomes: dict[str, dict]            # FamilyType.value → {param: mean_value}
    population_diversity: float              # mean coefficient of variation across genome params
    avg_turns: float
    avg_winner_hp_fraction: float


class Population:
    """Manages a collection of genome-parameterised agents across generations."""

    def __init__(
        self,
        agents: list[Agent],
        roster: list[Pokemon],
        team_mode: str = "random",
        rng: random.Random | None = None,
    ) -> None:
        self.agents = agents
        self.roster = roster
        self.team_mode = team_mode
        self.rng = rng or random.Random()

    def run_tournament(self) -> tuple[float, float]:
        """Round-robin: every agent battles every other agent once.

        Returns (avg_turns, avg_winner_hp_fraction) for the generation.
        """
        for agent in self.agents:
            agent.reset_record()

        all_turns: list[int] = []
        all_winner_hp_fractions: list[float] = []

        agent_pairs = [
            (self.agents[i], self.agents[j])
            for i in range(len(self.agents))
            for j in range(i + 1, len(self.agents))
        ]

        for agent_a, agent_b in agent_pairs:
            trainer_a = self._build_trainer(agent_a)
            trainer_b = self._build_trainer(agent_b)
            result = Battle(trainer_a, trainer_b, verbose=False).run()

            if result.winner is trainer_a:
                agent_a.wins += 1
                agent_b.losses += 1
            else:
                agent_b.wins += 1
                agent_a.losses += 1

            all_turns.append(result.turns)
            winner_team = result.winner.team
            all_winner_hp_fractions.append(
                sum(p.current_hp for p in winner_team) / max(1, sum(p.hp for p in winner_team))
            )

        avg_turns = sum(all_turns) / len(all_turns) if all_turns else 0.0
        avg_winner_hp = sum(all_winner_hp_fractions) / len(all_winner_hp_fractions) if all_winner_hp_fractions else 0.0
        return avg_turns, avg_winner_hp

    def evolve(self, mutation_rate: float) -> None:
        """Within-family reproduction: bottom 50% replaced by mutated offspring of top 50%."""
        families_present = {agent.family for agent in self.agents}

        for family in families_present:
            family_agents = [a for a in self.agents if a.family == family]
            if len(family_agents) < 2:
                continue

            family_agents.sort(key=lambda a: a.fitness, reverse=True)
            cutoff = max(1, len(family_agents) // 2)
            top_performers = family_agents[:cutoff]
            bottom_performers = family_agents[cutoff:]

            for agent_to_replace in bottom_performers:
                parent = self.rng.choice(top_performers)
                agent_to_replace.genome = mutate(parent.genome, mutation_rate, family)

    def run(
        self, generations: int, mutation_rate: float
    ) -> list[GenerationSnapshot]:
        """Run the full evolutionary loop and return per-generation snapshots."""
        snapshots: list[GenerationSnapshot] = []
        snapshots.append(self._snapshot(0, avg_turns=0.0, avg_winner_hp=0.0))

        for generation_number in range(1, generations + 1):
            avg_turns, avg_winner_hp = self.run_tournament()
            self.evolve(mutation_rate)
            snapshots.append(self._snapshot(generation_number, avg_turns, avg_winner_hp))

        return snapshots

    def _snapshot(
        self, generation: int, avg_turns: float, avg_winner_hp: float
    ) -> GenerationSnapshot:
        """Compute summary statistics for the current population state."""
        families_present = {agent.family for agent in self.agents}

        family_win_rates: dict[str, float] = {}
        mean_genomes: dict[str, dict] = {}

        for family in families_present:
            family_agents = [a for a in self.agents if a.family == family]
            total_games = sum(a.wins + a.losses for a in family_agents)
            total_wins = sum(a.wins for a in family_agents)
            family_win_rates[family.value] = total_wins / total_games if total_games > 0 else 0.0

            genome_params = _continuous_genome_params()
            mean_genomes[family.value] = {
                param: sum(getattr(a.genome, param) for a in family_agents) / len(family_agents)
                for param in genome_params
            }
            mean_genomes[family.value]["boost_threshold"] = (
                sum(a.genome.boost_threshold for a in family_agents) / len(family_agents)
            )

        population_diversity = _compute_diversity(self.agents)

        return GenerationSnapshot(
            generation=generation,
            family_win_rates=family_win_rates,
            mean_genomes=mean_genomes,
            population_diversity=population_diversity,
            avg_turns=avg_turns,
            avg_winner_hp_fraction=avg_winner_hp,
        )

    def _build_trainer(self, agent: Agent) -> Trainer:
        """Build a fresh Trainer with a newly sampled team for this battle."""
        archetype = FAMILY_ARCHETYPE.get(agent.family, "random")
        fresh_team = build_team(self.roster, archetype=archetype, rng=self.rng)
        return Trainer(
            name=agent.trainer_name,
            team=fresh_team,
            family=agent.family,
            genome=agent.genome,
            bag=dict(agent.initial_bag),
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_population(
    family_counts: dict[FamilyType, int],
    roster: list[Pokemon],
    team_mode: str = "random",
    initial_bag: dict[str, int] | None = None,
    rng: random.Random | None = None,
) -> Population:
    """Build a Population from a dict mapping FamilyType to agent count.

    Example: make_population({FamilyType.GREEDY: 10, FamilyType.STALL: 10}, roster)
    """
    rng = rng or random.Random()
    bag = initial_bag or {}
    agents: list[Agent] = []
    agent_counter = 0

    for family, count in family_counts.items():
        for _ in range(count):
            agents.append(Agent(
                trainer_name=f"{family.value}_{agent_counter}",
                family=family,
                genome=random_genome(family),
                initial_bag=dict(bag),
            ))
            agent_counter += 1

    rng.shuffle(agents)
    return Population(agents=agents, roster=roster, team_mode=team_mode, rng=rng)


# ---------------------------------------------------------------------------
# Diversity metric
# ---------------------------------------------------------------------------


def _continuous_genome_params() -> list[str]:
    return [
        "switch_threshold", "hp_heal_threshold", "item_use_chance",
        "uncertainty", "aggression", "protect_threshold",
        "status_priority", "setup_willingness",
    ]


def _compute_diversity(agents: list[Agent]) -> float:
    """Mean coefficient of variation across all continuous genome parameters."""
    if len(agents) < 2:
        return 0.0

    param_names = _continuous_genome_params()
    cv_values: list[float] = []

    for param in param_names:
        values = [getattr(a.genome, param) for a in agents]
        mean_value = sum(values) / len(values)
        if mean_value < 1e-6:
            continue
        std_value = statistics.pstdev(values)
        cv_values.append(std_value / mean_value)

    return sum(cv_values) / len(cv_values) if cv_values else 0.0

"""Evolutionary tournament infrastructure for genome-parameterised agents."""

from __future__ import annotations

import copy
import random
import statistics
from dataclasses import dataclass, field

from simulator.battle import Battle
from simulator.genome import FamilyType, Genome, mutate, random_genome
from simulator.items import ITEM_DATA
from simulator.pokemon import Pokemon
from simulator.team_builder import build_team
from simulator.trainer import Trainer


@dataclass
class Agent:
    """An evolvable participant — wraps a Trainer blueprint with fitness tracking."""

    trainer_name: str
    family: FamilyType
    genome: Genome
    roster: list[Pokemon]
    initial_bag: dict[str, int] = field(default_factory=dict)
    wins: int = 0
    losses: int = 0
    # Per-Pokémon accumulators — keyed by pokemon.name, reset each generation
    pokemon_kos: dict[str, int] = field(default_factory=dict)
    pokemon_turns_active: dict[str, int] = field(default_factory=dict)
    pokemon_stat_stages: dict[str, int] = field(default_factory=dict)
    pokemon_move_usage: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def fitness(self) -> float:
        """Win rate over all games played this generation; 0.0 if no games."""
        total_games = self.wins + self.losses
        return self.wins / total_games if total_games > 0 else 0.0

    def reset_record(self) -> None:
        """Clear wins/losses and per-Pokémon accumulators at the start of each generation."""
        self.wins = 0
        self.losses = 0
        self.pokemon_kos = {}
        self.pokemon_turns_active = {}
        self.pokemon_stat_stages = {}
        self.pokemon_move_usage = {}


@dataclass
class GenerationSnapshot:
    """Summary statistics recorded at the end of each generation."""

    generation: int
    family_win_rates: dict[str, float]       # FamilyType.value → mean win rate
    mean_genomes: dict[str, dict]            # FamilyType.value → {param: mean_value}
    population_diversity: float              # mean coefficient of variation across genome params
    avg_turns: float
    avg_winner_hp_fraction: float
    mean_roster_bst: dict[str, float]        # FamilyType.value → mean BST across all roster slots
    roster_diversity: dict[str, float]       # FamilyType.value → unique species / total slots


class Population:
    """Manages a collection of genome-parameterised agents across generations."""

    def __init__(
        self,
        agents: list[Agent],
        roster: list[Pokemon],
        team_mode: str = "random",
        roster_temperature: float = 1.0,
        move_mutation_rate: float = 0.3,
        rng: random.Random | None = None,
    ) -> None:
        self.agents = agents
        self.roster = roster
        self.team_mode = team_mode
        self.roster_temperature = roster_temperature
        self.move_mutation_rate = move_mutation_rate
        self.rng = rng or random.Random()
        self.pokemon_win_contributions: dict[str, int] = {}

    def run_tournament(self) -> tuple[float, float]:
        """Round-robin: every agent battles every other agent once.

        Returns (avg_turns, avg_winner_hp_fraction) for the generation.
        """
        for agent in self.agents:
            agent.reset_record()
        self.pokemon_win_contributions = {}

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
                winner_trainer = trainer_a
            else:
                agent_b.wins += 1
                agent_a.losses += 1
                winner_trainer = trainer_b

            _accumulate_pokemon_stats(agent_a, trainer_a.team)
            _accumulate_pokemon_stats(agent_b, trainer_b.team)

            for pokemon in winner_trainer.team:
                self.pokemon_win_contributions[pokemon.name] = (
                    self.pokemon_win_contributions.get(pokemon.name, 0) + 1
                )

            all_turns.append(result.turns)
            winner_team = result.winner.team
            all_winner_hp_fractions.append(
                sum(p.current_hp for p in winner_team) / max(1, sum(p.hp for p in winner_team))
            )

        avg_turns = sum(all_turns) / len(all_turns) if all_turns else 0.0
        avg_winner_hp = (
            sum(all_winner_hp_fractions) / len(all_winner_hp_fractions)
            if all_winner_hp_fractions
            else 0.0
        )
        return avg_turns, avg_winner_hp

    def evolve(self, mutation_rate: float) -> None:
        """Within-family: top 50% keep genome + roster; bottom 50% get both evolved."""
        families_present = {agent.family for agent in self.agents}

        for family in families_present:
            family_agents = [a for a in self.agents if a.family == family]
            if len(family_agents) < 2:
                continue

            family_agents.sort(key=lambda a: a.fitness, reverse=True)
            cutoff = max(1, len(family_agents) // 2)
            top_performers = family_agents[:cutoff]
            bottom_performers = family_agents[cutoff:]

            for losing_agent in bottom_performers:
                parent = self.rng.choice(top_performers)
                losing_agent.genome = mutate(parent.genome, mutation_rate, family)
                self._evolve_roster(losing_agent)

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
        mean_roster_bst: dict[str, float] = {}
        roster_diversity: dict[str, float] = {}

        for family in families_present:
            family_agents = [a for a in self.agents if a.family == family]
            total_games = sum(a.wins + a.losses for a in family_agents)
            total_wins = sum(a.wins for a in family_agents)
            family_win_rates[family.value] = (
                total_wins / total_games if total_games > 0 else 0.0
            )

            genome_params = _continuous_genome_params()
            mean_genomes[family.value] = {
                param: sum(getattr(a.genome, param) for a in family_agents) / len(family_agents)
                for param in genome_params
            }
            mean_genomes[family.value]["boost_threshold"] = (
                sum(a.genome.boost_threshold for a in family_agents) / len(family_agents)
            )

            all_roster_pokemon = [p for a in family_agents for p in a.roster]
            mean_roster_bst[family.value] = (
                sum(p.bst for p in all_roster_pokemon) / len(all_roster_pokemon)
                if all_roster_pokemon
                else 0.0
            )

            total_slots = len(family_agents) * 6
            unique_names = {p.name for p in all_roster_pokemon}
            roster_diversity[family.value] = (
                len(unique_names) / total_slots if total_slots > 0 else 0.0
            )

        population_diversity = _compute_diversity(self.agents)

        return GenerationSnapshot(
            generation=generation,
            family_win_rates=family_win_rates,
            mean_genomes=mean_genomes,
            population_diversity=population_diversity,
            avg_turns=avg_turns,
            avg_winner_hp_fraction=avg_winner_hp,
            mean_roster_bst=mean_roster_bst,
            roster_diversity=roster_diversity,
        )

    def _build_trainer(self, agent: Agent) -> Trainer:
        """Build a Trainer using the agent's persistent roster; reset battle state only."""
        fresh_team = [copy.deepcopy(p) for p in agent.roster]
        for pokemon in fresh_team:
            pokemon.reset_battle_state()
        return Trainer(
            name=agent.trainer_name,
            team=fresh_team,
            family=agent.family,
            genome=agent.genome,
            bag=dict(agent.initial_bag),
        )

    def _evolve_roster(self, agent: Agent) -> None:
        """Cut the weakest Pokémon from a losing agent's roster and sample a replacement."""
        cut_name = _cut_pokemon(agent, self.rng)
        agent.roster = [p for p in agent.roster if p.name != cut_name]

        replacement = _sample_replacement(
            self.roster,
            self.pokemon_win_contributions,
            self.roster_temperature,
            self.rng,
        )
        agent.roster.append(replacement)

        # Move mutation for the 5 kept Pokémon; replacement already has fresh moves
        for pokemon in agent.roster[:-1]:
            usage = agent.pokemon_move_usage.get(pokemon.name, {})
            _evolve_moveset(pokemon, usage, self.move_mutation_rate, self.rng)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_population(
    family_counts: dict[FamilyType, int],
    roster: list[Pokemon],
    team_mode: str = "random",
    initial_bag: dict[str, int] | None = None,
    roster_temperature: float = 1.0,
    move_mutation_rate: float = 0.3,
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
            agents.append(
                Agent(
                    trainer_name=f"{family.value}_{agent_counter}",
                    family=family,
                    genome=random_genome(family),
                    roster=build_team(roster, rng=rng),
                    initial_bag=dict(bag),
                )
            )
            agent_counter += 1

    rng.shuffle(agents)
    return Population(
        agents=agents,
        roster=roster,
        team_mode=team_mode,
        roster_temperature=roster_temperature,
        move_mutation_rate=move_mutation_rate,
        rng=rng,
    )


# ---------------------------------------------------------------------------
# Roster evolution helpers
# ---------------------------------------------------------------------------


def _cut_pokemon(agent: Agent, rng: random.Random) -> str:
    """Return the name of the Pokémon to cut based on the agent's family fitness signal."""
    names = [p.name for p in agent.roster]

    if agent.family == FamilyType.RANDOM:
        return rng.choice(names)

    if agent.family == FamilyType.GREEDY:
        scores = {name: agent.pokemon_kos.get(name, 0) for name in names}
    elif agent.family == FamilyType.STALL:
        scores = {name: agent.pokemon_turns_active.get(name, 0) for name in names}
    elif agent.family == FamilyType.SETUP:
        scores = {name: agent.pokemon_stat_stages.get(name, 0) for name in names}
    else:
        return rng.choice(names)

    min_score = min(scores.values())
    candidates = [name for name, score in scores.items() if score == min_score]
    return rng.choice(candidates)


def _sample_replacement(
    pool: list[Pokemon],
    win_contributions: dict[str, int],
    temperature: float,
    rng: random.Random,
) -> Pokemon:
    """Sample a replacement Pokémon from the global pool weighted by win contributions.

    High temperature → near-uniform sampling. Low temperature → top contributors dominate.
    """
    weights = [
        (win_contributions.get(p.name, 0) + 1) ** (1.0 / max(temperature, 1e-6))
        for p in pool
    ]
    chosen = rng.choices(pool, weights=weights, k=1)[0]
    replacement = copy.deepcopy(chosen)
    pool_moves = replacement.move_pool if replacement.move_pool else replacement.moveset
    replacement.moveset = rng.sample(pool_moves, min(4, len(pool_moves)))
    replacement.held_item = rng.choice(list(ITEM_DATA.keys()))
    return replacement


def _evolve_moveset(
    pokemon: Pokemon,
    move_usage: dict[str, int],
    move_mutation_rate: float,
    rng: random.Random,
) -> None:
    """Discard the least-used active move and replace it with a random unused pool move."""
    if rng.random() >= move_mutation_rate:
        return
    unused_moves = [m for m in pokemon.move_pool if m not in pokemon.moveset]
    if not unused_moves:
        return
    worst_move = min(pokemon.moveset, key=lambda m: move_usage.get(m.name, 0))
    pokemon.moveset.remove(worst_move)
    pokemon.moveset.append(rng.choice(unused_moves))


# ---------------------------------------------------------------------------
# Stat accumulation
# ---------------------------------------------------------------------------


def _accumulate_pokemon_stats(agent: Agent, team: list[Pokemon]) -> None:
    """Fold per-Pokémon battle stats from a completed battle into the agent's accumulators."""
    for pokemon in team:
        name = pokemon.name
        agent.pokemon_kos[name] = agent.pokemon_kos.get(name, 0) + pokemon.kos_dealt
        agent.pokemon_turns_active[name] = (
            agent.pokemon_turns_active.get(name, 0) + pokemon.turns_active
        )
        agent.pokemon_stat_stages[name] = (
            agent.pokemon_stat_stages.get(name, 0) + pokemon.stat_stages_gained
        )
        if name not in agent.pokemon_move_usage:
            agent.pokemon_move_usage[name] = {}
        for move_name, count in pokemon.move_usage.items():
            agent.pokemon_move_usage[name][move_name] = (
                agent.pokemon_move_usage[name].get(move_name, 0) + count
            )


# ---------------------------------------------------------------------------
# Diversity metrics
# ---------------------------------------------------------------------------


def _continuous_genome_params() -> list[str]:
    return [
        "switch_threshold",
        "hp_heal_threshold",
        "item_use_chance",
        "uncertainty",
        "aggression",
        "protect_threshold",
        "status_priority",
        "setup_willingness",
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

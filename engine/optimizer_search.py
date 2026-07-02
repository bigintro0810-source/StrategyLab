"""Alternative parameter-search strategies over the existing discrete grid.

engine/optimizer.py and engine/fast_optimizer.py (pre-existing, unconnected
"future asset" modules) turned out to be broken (ImportError on a
Result/BacktestResult name mismatch) and, more importantly, are just
alternative execution engines for exhaustive grid search - they don't
implement random search or a genetic algorithm. So this module is a fresh,
dependency-free implementation (no optuna/deap installed, no
requirements.txt in the repo) rather than a reuse of that code.
"""

import random


def sample_random_combos(
    param_space: dict[str, list],
    n_samples: int,
    seed: int = 42,
) -> list[dict]:
    rng = random.Random(seed)
    seen = set()
    combos = []
    max_attempts = max(n_samples * 50, 1000)
    attempts = 0

    while len(combos) < n_samples and attempts < max_attempts:
        attempts += 1
        combo = {key: rng.choice(values) for key, values in param_space.items()}
        signature = tuple(sorted(combo.items()))
        if signature in seen:
            continue
        seen.add(signature)
        combos.append(combo)

    return combos


def _random_individual(param_space: dict[str, list], rng: random.Random) -> dict:
    return {key: rng.choice(values) for key, values in param_space.items()}


def _crossover(parent_a: dict, parent_b: dict, rng: random.Random) -> dict:
    return {
        key: (parent_a[key] if rng.random() < 0.5 else parent_b[key])
        for key in parent_a
    }


def _mutate(
    individual: dict,
    param_space: dict[str, list],
    rng: random.Random,
    mutation_rate: float,
) -> dict:
    mutated = dict(individual)
    for key, values in param_space.items():
        if rng.random() < mutation_rate:
            mutated[key] = rng.choice(values)
    return mutated


def _tournament_select(
    scored_population: list[tuple[float, dict]],
    rng: random.Random,
    k: int = 3,
) -> dict:
    contenders = rng.sample(scored_population, min(k, len(scored_population)))
    return max(contenders, key=lambda pair: pair[0])[1]


class GeneticSearch:
    """Small custom GA over a discrete parameter grid.

    Each "gene" is one parameter, drawn from the same discrete value list
    build_parameter_grid() would otherwise take a full cartesian product of.
    Caller drives the generation loop (evaluate a population, then feed the
    scored results back in) so evaluation can stay parallelized through the
    existing ProcessPoolExecutor pattern in main.py.
    """

    def __init__(
        self,
        param_space: dict[str, list],
        population_size: int = 20,
        elite_count: int = 2,
        mutation_rate: float = 0.2,
        seed: int = 42,
    ):
        self.param_space = param_space
        self.population_size = population_size
        self.elite_count = elite_count
        self.mutation_rate = mutation_rate
        self.rng = random.Random(seed)

    def initial_population(self) -> list[dict]:
        return [
            _random_individual(self.param_space, self.rng)
            for _ in range(self.population_size)
        ]

    def next_population(self, scored_population: list[tuple[float, dict]]) -> list[dict]:
        ranked = sorted(scored_population, key=lambda pair: pair[0], reverse=True)
        next_gen = [individual for _, individual in ranked[: self.elite_count]]

        while len(next_gen) < self.population_size:
            parent_a = _tournament_select(scored_population, self.rng)
            parent_b = _tournament_select(scored_population, self.rng)
            child = _crossover(parent_a, parent_b, self.rng)
            child = _mutate(child, self.param_space, self.rng, self.mutation_rate)
            next_gen.append(child)

        return next_gen

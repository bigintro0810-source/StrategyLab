"""Alternative parameter-search strategies over the existing discrete grid.

engine/optimizer.py and engine/fast_optimizer.py (pre-existing, unconnected
"future asset" modules) turned out to be broken (ImportError on a
Result/BacktestResult name mismatch) and, more importantly, are just
alternative execution engines for exhaustive grid search - they don't
implement random search, a genetic algorithm, or Bayesian optimization.
So this module is a fresh implementation rather than a reuse of that code.

sample_random_combos()/GeneticSearch are dependency-free by design.
run_bayesian_search() is the exception - it uses optuna (added 2026-07-03,
this repo's second real third-party dependency after streamlit), since
hand-rolling a Gaussian process well enough to be worth trusting isn't a
reasonable use of time versus a well-maintained library built for exactly
this. optuna was chosen over scikit-optimize/hyperopt because this
project's parameter space is a large mix of categorical (entry_trigger),
boolean, integer, and float keys - optuna's define-by-run suggest_*() API
handles that natively, where skopt is oriented around continuous/
numeric-heavy spaces.
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


def run_bayesian_search(
    df,
    is_intraday: bool,
    param_space: dict[str, list],
    n_trials: int,
    stability_fn,
    advanced_metrics_fn,
    seed: int = 42,
    progress_callback=None,
) -> list[dict]:
    """Sequential Bayesian search (optuna's TPE sampler) over param_space.

    Unlike grid/random (one big batch submitted to a ProcessPoolExecutor)
    or genetic (per-generation batches), this runs run_backtest() directly
    in the calling process, one trial at a time - each trial's parameter
    suggestion depends on every prior trial's result, so there's no
    natural batch to parallelize across worker processes without
    weakening the "Bayesian" part (evaluating many trials before
    incorporating feedback is closer to random search). A single backtest
    call is a few seconds at most on non-1m timeframes, so n_trials in the
    tens-to-low-hundreds runs in a reasonable time sequentially.

    Every param_space key is treated as categorical (trial.suggest_
    categorical over its existing discrete value list), matching what
    grid/random/genetic already sample from - Bayesian mode explores the
    same space, just with smarter trial selection instead of exhaustive/
    random/evolutionary selection.

    stability_fn(trade_log) -> dict and advanced_metrics_fn(trade_log) -> dict
    are injected rather than imported directly, since they live in
    main.py (calculate_stability_metrics/calculate_advanced_metrics) and
    main.py already imports this module - importing back would be
    circular. Every other optimizer path (main.py::run_one_backtest, used
    by grid/random/genetic) computes these same fields before returning a
    result; skipping them here would silently break export_rankings()
    (sorts on overall_stability_score) the same way an earlier version of
    this function did before stability_fn was added - advanced_metrics_fn
    follows the same fix preemptively rather than waiting to hit the same
    bug twice.
    """
    import optuna
    from engine.backtest_engine import run_backtest

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: "optuna.Trial") -> float:
        params = {
            key: trial.suggest_categorical(key, values) for key, values in param_space.items()
        }

        result, trade_log = run_backtest(
            df=df, params=params, return_trades=True, is_intraday=is_intraday
        )
        stability = stability_fn(trade_log)
        result["yearly_stability_score"] = stability["yearly_stability_score"]
        result["monthly_stability_score"] = stability["monthly_stability_score"]
        result["overall_stability_score"] = stability["overall_stability_score"]
        result["stability_rating"] = stability["rating"]

        advanced = advanced_metrics_fn(trade_log)
        result["sharpe_ratio"] = advanced["sharpe_ratio"]
        result["sortino_ratio"] = advanced["sortino_ratio"]
        result["cagr"] = advanced["cagr"]
        result["calmar_ratio"] = advanced["calmar_ratio"]

        trial.set_user_attr("result", result)

        if progress_callback is not None:
            progress_callback(trial.number + 1, n_trials)

        return result["profit_factor"]

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials)

    results = []
    for param_id, trial in enumerate(study.trials, start=1):
        result = dict(trial.user_attrs["result"])
        result["param_id"] = param_id
        results.append(result)

    return results

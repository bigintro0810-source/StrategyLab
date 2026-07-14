"""Phase 1 of the auto-exploration engine: generates candidate condition
trees (which indicators, how they nest under AND/OR/NOT, and their own
parameter values) from engine/indicator_pool.py's pool - rather than a
human assembling one tree by hand in the dashboard's manual builder.

This is a pure, dependency-free module (same design principle as
engine/optimizer_search.py) - it only builds engine/conditions.py
Condition/ConditionGroup trees and serializes them to plain dicts. It does
not run backtests and does not touch engine/backtest_engine.py at all: the
output is a list of dicts in exactly the shape evaluate_condition_tree()
already consumes, so it plugs into main.py's existing condition_tree
param_space mechanism (the same one the dashboard's node-level parameter
sweep already uses) with no changes to the execution/ranking pipeline.

Also contains StructureGeneticSearch (MVP2): evolves these trees via
crossover (subtree swap) and mutation (leaf regeneration / AND<->OR flip /
direction flip), the structural equivalent of
engine/optimizer_search.py's GeneticSearch - that class evolves scalar
parameter values, this one evolves the tree shape itself. See its
docstring for why fitness must penalize low trade counts before being fed
in, not after.

Multi-timeframe generation: mtf_timeframes/mtf_probability (both off by
default) let a generated leaf's own timeframe/value_timeframe reference a
coarser timeframe than the backtest's base (see coarser_timeframes()) - the
engine itself has supported this per-Condition since the dashboard's manual
builder got it; this only adds the ability to GENERATE it automatically.

Deliberately NOT implemented yet (see project_auto_exploration_core_goal.md
for the staged plan):
    - logical-contradiction pruning (e.g. rsi<30 AND rsi>70) - left to the
      ranking step / GA fitness, which naturally sinks a zero-trade
      candidate to the bottom
    - simultaneous long+short tree generation
    - automatic Phase-1(this)->Phase-2(optimizer_search.py) handoff
"""

from __future__ import annotations

import copy
import json
import random

from engine.conditions import Condition, ConditionGroup
from engine.indicator_pool import INDICATOR_POOL, OPERATORS_BY_KIND, IndicatorSpec, pool_by_kind

_GROUP_OPS = ["AND", "OR", "NOT"]
_GROUP_OP_WEIGHTS = [0.55, 0.30, 0.15]
_INDICATOR_PAIR_PROB = 0.5

# Ordered finest-to-coarsest, matching main.py's AVAILABLE_TIMEFRAMES - kept
# as a local literal rather than importing main.py (which imports this
# module) to avoid a circular import for what is otherwise a static list.
_TIMEFRAME_ORDER = ["1m", "5m", "10m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]


def coarser_timeframes(base_timeframe: str) -> list[str]:
    """Every known timeframe strictly coarser than base_timeframe - the only
    sane direction for MTF generation (filtering a lower-timeframe entry
    signal by a HIGHER-timeframe condition, e.g. 15m entries filtered by a
    1h/4h/1d trend - not the reverse, which the engine mechanically allows
    but has no real trading rationale for). Returns [] for an unrecognized
    or already-coarsest base_timeframe."""
    if base_timeframe not in _TIMEFRAME_ORDER:
        return []
    return _TIMEFRAME_ORDER[_TIMEFRAME_ORDER.index(base_timeframe) + 1 :]


def _sample_params(
    spec: IndicatorSpec,
    rng: random.Random,
    allowed_param_values: dict[str, dict[str, list]] | None = None,
) -> dict:
    """Samples each param_ranges key from (in priority order): the caller's
    per-run selection for this indicator+param (allowed_param_values, from
    the auto-exploration screen's value checkboxes), else the indicator's
    own value_presets (indicator_pool.py's representative-value template),
    else the raw continuous range as a last-resort fallback (only reachable
    if value_presets was somehow left empty for that param)."""
    own_allowed = (allowed_param_values or {}).get(spec.name, {})
    params = {}
    for name, (lo, hi) in spec.param_ranges.items():
        choices = own_allowed.get(name) or spec.value_presets.get(name) or list(range(int(lo), int(hi) + 1))
        params[name] = rng.choice(choices)
    params.update({name: rng.choice(choices) for name, choices in spec.param_choices.items()})
    return params


def _sample_literal(
    spec: IndicatorSpec,
    rng: random.Random,
    allowed_literal_values: dict[str, list] | None = None,
) -> float:
    own_allowed = (allowed_literal_values or {}).get(spec.name)
    if own_allowed:
        return rng.choice(own_allowed)
    if spec.literal_choices is not None:
        return rng.choice(spec.literal_choices)
    if spec.literal_presets:
        return rng.choice(spec.literal_presets)
    lo, hi = spec.literal_range
    if spec.literal_is_int:
        return float(rng.randint(int(lo), int(hi)))
    return rng.uniform(lo, hi)


def _pick_value_side(
    spec: IndicatorSpec,
    own_params: dict,
    grouped: dict[str, list[IndicatorSpec]],
    rng: random.Random,
    allowed_param_values: dict[str, dict[str, list]] | None = None,
    allowed_literal_values: dict[str, list] | None = None,
) -> tuple[float | str, dict]:
    """Returns (value, value_params) for a Condition whose left side is spec/own_params.

    price_level indicators have no literal_range at all (see
    indicator_pool.py), so they always take the indicator-pair branch.
    Kinds with both a literal range and allow_indicator_pair (rsi, adx)
    pick between the two by coin flip - both are meaningful (e.g.
    "rsi > 70" and "rsi(14) > rsi(50)" are both sane conditions)."""
    has_literal = spec.literal_range is not None or spec.literal_choices is not None
    use_indicator_pair = spec.allow_indicator_pair and (
        not has_literal or rng.random() < _INDICATOR_PAIR_PROB
    )

    if not use_indicator_pair:
        return _sample_literal(spec, rng, allowed_literal_values), {}

    candidates = grouped[spec.kind]
    own_signature = (spec.name, tuple(sorted(own_params.items())))

    for _ in range(20):
        other = rng.choice(candidates)
        other_params = _sample_params(other, rng, allowed_param_values)
        if (other.name, tuple(sorted(other_params.items()))) != own_signature:
            return other.name, other_params

    # 20 retries exhausted (only happens with a tiny same-kind pool and
    # narrow ranges) - fall back to a literal if available, otherwise
    # accept the self-pair. A self-pair condition is either always-false
    # (>, <) or always-true (==), which the ranking step naturally sinks
    # via zero/near-total trade count - not worth a hard failure here.
    if has_literal:
        return _sample_literal(spec, rng, allowed_literal_values), {}
    return other.name, other_params


def _generate_leaf(
    rng: random.Random,
    grouped: dict[str, list[IndicatorSpec]],
    pool: list[IndicatorSpec],
    mtf_timeframes: list[str] | None = None,
    mtf_probability: float = 0.0,
    allowed_param_values: dict[str, dict[str, list]] | None = None,
    allowed_literal_values: dict[str, list] | None = None,
) -> Condition:
    spec = rng.choice(pool)
    own_params = _sample_params(spec, rng, allowed_param_values)
    operator = rng.choice(OPERATORS_BY_KIND[spec.kind])
    value, value_params = _pick_value_side(
        spec, own_params, grouped, rng, allowed_param_values, allowed_literal_values
    )

    # Each side independently may reference a coarser timeframe than the
    # backtest's own base - e.g. a 15m entry filtered by a 1h/4h/1d EMA, or
    # a cross-timeframe indicator-pair like "1h RSI vs 4h RSI". Left at
    # mtf_probability=0.0 by default (main.py only enables this when
    # explicitly requested via --mtf-probability), so existing callers/
    # tests that never pass these two args keep generating single-timeframe
    # trees exactly as before.
    timeframe = None
    value_timeframe = None
    if mtf_timeframes and rng.random() < mtf_probability:
        timeframe = rng.choice(mtf_timeframes)
    if mtf_timeframes and isinstance(value, str) and rng.random() < mtf_probability:
        value_timeframe = rng.choice(mtf_timeframes)

    return Condition(
        indicator=spec.name,
        operator=operator,
        value=value,
        params=own_params,
        value_params=value_params,
        timeframe=timeframe,
        value_timeframe=value_timeframe,
    )


def _generate_node(
    rng: random.Random,
    grouped: dict[str, list[IndicatorSpec]],
    pool: list[IndicatorSpec],
    depth: int,
    max_depth: int,
    leaves_left: list[int],
    mtf_timeframes: list[str] | None = None,
    mtf_probability: float = 0.0,
    allowed_param_values: dict[str, dict[str, list]] | None = None,
    allowed_literal_values: dict[str, list] | None = None,
) -> Condition | ConditionGroup:
    """leaves_left is a 1-element list used as a mutable shared budget across
    the recursion - a plain int can't be decremented by a nested call and
    have the caller see the update. Once the budget reaches 1, this and every
    subsequent call return a leaf instead of recursing, capping the tree's
    total condition count (max_leaves is therefore a soft cap: a group node
    that has already committed to >=2 children can still exceed it by one or
    two conditions in the worst case, not worth guarding against precisely
    for an MVP screening pass)."""
    leaf_kwargs = dict(
        mtf_timeframes=mtf_timeframes,
        mtf_probability=mtf_probability,
        allowed_param_values=allowed_param_values,
        allowed_literal_values=allowed_literal_values,
    )
    if depth >= max_depth or leaves_left[0] <= 1:
        leaves_left[0] -= 1
        return _generate_leaf(rng, grouped, pool, **leaf_kwargs)

    op = rng.choices(_GROUP_OPS, weights=_GROUP_OP_WEIGHTS)[0]
    n_children = 1 if op == "NOT" else rng.choice([2, 2, 3])

    children: list[Condition | ConditionGroup] = []
    for _ in range(n_children):
        if leaves_left[0] <= 1:
            children.append(_generate_leaf(rng, grouped, pool, **leaf_kwargs))
            leaves_left[0] -= 1
        elif rng.random() < 0.5:
            children.append(
                _generate_node(
                    rng, grouped, pool, depth + 1, max_depth, leaves_left,
                    mtf_timeframes, mtf_probability, allowed_param_values, allowed_literal_values,
                )
            )
        else:
            children.append(_generate_leaf(rng, grouped, pool, **leaf_kwargs))
            leaves_left[0] -= 1

    return ConditionGroup(op=op, children=children)


def generate_random_tree(
    rng: random.Random,
    max_depth: int = 2,
    min_leaves: int = 1,
    max_leaves: int = 4,
    mtf_timeframes: list[str] | None = None,
    mtf_probability: float = 0.0,
    pool: list[IndicatorSpec] | None = None,
    allowed_param_values: dict[str, dict[str, list]] | None = None,
    allowed_literal_values: dict[str, list] | None = None,
) -> Condition | ConditionGroup:
    pool = pool if pool is not None else INDICATOR_POOL
    grouped = pool_by_kind(pool)
    leaves_left = [rng.randint(min_leaves, max_leaves)]
    return _generate_node(
        rng, grouped, pool, depth=0, max_depth=max_depth, leaves_left=leaves_left,
        mtf_timeframes=mtf_timeframes, mtf_probability=mtf_probability,
        allowed_param_values=allowed_param_values, allowed_literal_values=allowed_literal_values,
    )


def generate_candidate_trees(
    n: int,
    seed: int = 42,
    max_depth: int = 2,
    min_leaves: int = 1,
    max_leaves: int = 4,
    mtf_timeframes: list[str] | None = None,
    mtf_probability: float = 0.0,
    pool: list[IndicatorSpec] | None = None,
    allowed_param_values: dict[str, dict[str, list]] | None = None,
    allowed_literal_values: dict[str, list] | None = None,
) -> list[dict]:
    """Generates up to n structurally-distinct condition trees, as plain
    dicts ready to drop into a condition_tree param_space list (see main.py's
    --optimizer structure mode).

    mtf_timeframes/mtf_probability (both off by default) let a leaf's
    indicator - or its comparison value, if that's also an indicator -
    reference a coarser timeframe than the backtest's own base (see
    coarser_timeframes()) - e.g. a 15m entry filtered by a 1h/4h/1d
    condition. The engine already supports this per-Condition (see
    engine/conditions.py's timeframe/value_timeframe fields, used by the
    dashboard's manual builder) - this only adds the ability to generate it.

    Deduplicates by exact structural equality (same bounded-retry pattern as
    engine/optimizer_search.py's sample_random_combos, since a narrow pool
    can exhaust distinct trees well before n is reached - looping forever
    waiting for a uniqueness that can't happen would hang the CLI)."""
    if pool is not None and len(pool) == 0:
        raise ValueError(
            "選択した条件カテゴリ/探索レベルに該当する指標が1つもありません。"
            "カテゴリを1つ以上有効にしてください。"
        )
    rng = random.Random(seed)
    seen: set[str] = set()
    trees: list[dict] = []
    max_attempts = max(n * 20, 1000)
    attempts = 0

    while len(trees) < n and attempts < max_attempts:
        attempts += 1
        tree = generate_random_tree(
            rng, max_depth=max_depth, min_leaves=min_leaves, max_leaves=max_leaves,
            mtf_timeframes=mtf_timeframes, mtf_probability=mtf_probability, pool=pool,
            allowed_param_values=allowed_param_values, allowed_literal_values=allowed_literal_values,
        )
        tree_dict = tree.to_dict()
        signature = json.dumps(tree_dict, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        trees.append(tree_dict)

    return trees


def wrap_with_mandatory_conditions(tree: dict, mandatory_conditions: list[dict] | None) -> dict:
    """AND-combines mandatory_conditions (a run-level constant, the same for
    every candidate) onto a generated tree. Deliberately applied here, at
    the boundary between generation and evaluation, rather than spliced into
    the random tree itself: mandatory conditions must survive crossover/
    mutation unchanged, and both of those operate on whatever
    individual["condition_tree"] holds. Keeping the constant entirely
    outside that field means _crossover/_mutate never need to know it
    exists - callers wrap right before backtesting instead (main.py's
    structure/structure_genetic branches)."""
    if not mandatory_conditions:
        return tree
    return {"op": "AND", "children": [*copy.deepcopy(mandatory_conditions), tree]}


# ---------------------------------------------------------------------------
# MVP2: structural genetic algorithm (crossover/mutation of trees themselves)
# ---------------------------------------------------------------------------


def _is_group(node: dict) -> bool:
    return "op" in node


def _enumerate_paths(node: dict, path: tuple[int, ...] = ()) -> list[tuple[int, ...]]:
    """Every node's address as a tuple of child-indices from the root
    (empty tuple = the root itself) - used to pick a random cut point for
    crossover without needing parent back-pointers on plain dicts."""
    paths = [path]
    if _is_group(node):
        for index, child in enumerate(node["children"]):
            paths.extend(_enumerate_paths(child, path + (index,)))
    return paths


def _get_node_at_path(tree: dict, path: tuple[int, ...]) -> dict:
    node = tree
    for index in path:
        node = node["children"][index]
    return node


def _replace_node_at_path(tree: dict, path: tuple[int, ...], new_node: dict) -> dict:
    if not path:
        return copy.deepcopy(new_node)
    new_tree = copy.deepcopy(tree)
    node = new_tree
    for index in path[:-1]:
        node = node["children"][index]
    node["children"][path[-1]] = copy.deepcopy(new_node)
    return new_tree


def _count_leaves(node: dict) -> int:
    if not _is_group(node):
        return 1
    return sum(_count_leaves(child) for child in node["children"])


def _tree_depth(node: dict) -> int:
    if not _is_group(node):
        return 0
    return 1 + max((_tree_depth(child) for child in node["children"]), default=0)


def _crossover(
    parent_a: dict, parent_b: dict, rng: random.Random, max_leaves: int, max_depth: int
) -> dict:
    """Swaps a randomly-chosen subtree of parent_a's condition_tree with a
    randomly-chosen subtree of parent_b's. Retries with a fresh pair of cut
    points if the result overshoots a permissive 2x size budget (real GA
    "bloat" control would track this exactly; a single-crossover-point tree
    rarely runs away that far, so a loose retry is enough for this MVP
    pass), falling back to parent_a unchanged if still oversized after a
    few tries rather than looping indefinitely."""
    tree_a, tree_b = parent_a["condition_tree"], parent_b["condition_tree"]
    paths_a = _enumerate_paths(tree_a)
    paths_b = _enumerate_paths(tree_b)

    for _ in range(5):
        path_a = rng.choice(paths_a)
        path_b = rng.choice(paths_b)
        subtree_b = _get_node_at_path(tree_b, path_b)
        child_tree = _replace_node_at_path(tree_a, path_a, subtree_b)
        if _count_leaves(child_tree) <= max_leaves * 2 and _tree_depth(child_tree) <= max_depth + 2:
            direction = rng.choice([parent_a["direction"], parent_b["direction"]])
            child = {"condition_tree": child_tree, "direction": direction}
            # rr only evolves in full mode (see StructureGeneticSearch's
            # rr_choices) - both parents always have it or neither does, so
            # checking parent_a alone is enough.
            if "rr" in parent_a:
                child["rr"] = rng.choice([parent_a["rr"], parent_b["rr"]])
            return child

    return copy.deepcopy(parent_a)


def _mutate(
    individual: dict,
    rng: random.Random,
    grouped: dict[str, list[IndicatorSpec]],
    pool: list[IndicatorSpec],
    mutation_rate: float,
    mtf_timeframes: list[str] | None = None,
    mtf_probability: float = 0.0,
    rr_choices: list[float] | None = None,
    allowed_param_values: dict[str, dict[str, list]] | None = None,
    allowed_literal_values: dict[str, list] | None = None,
    allowed_directions: list[str] | None = None,
) -> dict:
    """Leaf mutation (replace with a freshly generated leaf) and group
    mutation (flip AND<->OR, NOT excluded since it's locked to exactly one
    child) each apply independently per-node at mutation_rate - the tree
    equivalent of engine/optimizer_search.py's scalar _mutate() (per-key
    coin flip). direction flips independently at a quarter of mutation_rate
    since long<->short is a much bigger behavioral jump than tweaking one
    condition - skipped entirely when allowed_directions restricts the run
    to a single direction, since there's nothing to flip to."""
    tree = copy.deepcopy(individual["condition_tree"])

    def _walk(node: dict) -> dict:
        if _is_group(node):
            if node["op"] in ("AND", "OR") and rng.random() < mutation_rate:
                node["op"] = "OR" if node["op"] == "AND" else "AND"
            node["children"] = [_walk(child) for child in node["children"]]
            return node
        if rng.random() < mutation_rate:
            return _generate_leaf(
                rng, grouped, pool, mtf_timeframes, mtf_probability,
                allowed_param_values, allowed_literal_values,
            ).to_dict()
        return node

    mutated_tree = _walk(tree)
    direction = individual["direction"]
    if (allowed_directions is None or len(allowed_directions) > 1) and rng.random() < mutation_rate / 4:
        direction = "short" if direction == "long" else "long"

    result = {"condition_tree": mutated_tree, "direction": direction}
    if "rr" in individual:
        rr = individual["rr"]
        if rr_choices and rng.random() < mutation_rate:
            rr = rng.choice(rr_choices)
        result["rr"] = rr
    return result


def _tournament_select(scored_population: list[tuple[float, dict]], rng: random.Random, k: int = 3) -> dict:
    contenders = rng.sample(scored_population, min(k, len(scored_population)))
    return max(contenders, key=lambda pair: pair[0])[1]


class StructureGeneticSearch:
    """Evolves condition_tree structures - engine/optimizer_search.py's
    GeneticSearch evolves scalar parameter values instead, over a fixed
    structure. Each individual is {"condition_tree": dict, "direction":
    "long"|"short"}.

    The caller (main.py's --optimizer structure_genetic) drives the
    generation loop exactly like GeneticSearch: evaluate a population via
    the existing ProcessPoolExecutor/run_batch path, then feed
    (fitness, individual) pairs back into next_population().

    Fitness MUST already penalize low trade counts before being passed in
    (main.py does: profit_factor if trades >= min_trades else 0.0) -
    profit_factor and overall_stability_score both cap out at their maximum
    for a 1-3 trade all-winners candidate (see MVP1's finding in
    project_auto_exploration_core_goal.md). A GA's whole selection pressure
    would otherwise converge the entire population onto that degenerate
    exploit within a few generations - far worse than one-shot random
    screening, where it only pollutes the top of a ranking rather than
    actively breeding toward it."""

    def __init__(
        self,
        population_size: int = 20,
        elite_count: int = 2,
        mutation_rate: float = 0.2,
        max_depth: int = 2,
        max_leaves: int = 4,
        min_leaves: int = 1,
        seed: int = 42,
        mtf_timeframes: list[str] | None = None,
        mtf_probability: float = 0.0,
        pool: list[IndicatorSpec] | None = None,
        rr_choices: list[float] | None = None,
        allowed_param_values: dict[str, dict[str, list]] | None = None,
        allowed_literal_values: dict[str, list] | None = None,
        allowed_directions: list[str] | None = None,
    ):
        if pool is not None and len(pool) == 0:
            raise ValueError(
                "選択した条件カテゴリ/探索レベルに該当する指標が1つもありません。"
                "カテゴリを1つ以上有効にしてください。"
            )
        self.population_size = population_size
        self.elite_count = elite_count
        self.mutation_rate = mutation_rate
        self.max_depth = max_depth
        self.max_leaves = max_leaves
        self.min_leaves = min_leaves
        self.mtf_timeframes = mtf_timeframes
        self.mtf_probability = mtf_probability
        self.pool = pool if pool is not None else INDICATOR_POOL
        self.rng = random.Random(seed)
        self.grouped = pool_by_kind(self.pool)
        # RR(利確のリスクリワード比)を条件ツリーと一緒に進化させるかどうか。
        # Noneまたは要素数1(devモード相当)なら今まで通りmain.py側の
        # base_defaults固定値のみを使い、個体には"rr"キーを持たせない。
        # 2要素以上(fullモード)のときだけ個体ごとにRRも交叉・突然変異させる。
        self.rr_choices = rr_choices if rr_choices and len(rr_choices) > 1 else None
        self.allowed_param_values = allowed_param_values
        self.allowed_literal_values = allowed_literal_values
        self.allowed_directions = allowed_directions or ["long", "short"]

    def _random_individual(self) -> dict:
        tree = generate_random_tree(
            self.rng, max_depth=self.max_depth, min_leaves=self.min_leaves, max_leaves=self.max_leaves,
            mtf_timeframes=self.mtf_timeframes, mtf_probability=self.mtf_probability, pool=self.pool,
            allowed_param_values=self.allowed_param_values, allowed_literal_values=self.allowed_literal_values,
        ).to_dict()
        direction = self.rng.choice(self.allowed_directions)
        individual = {"condition_tree": tree, "direction": direction}
        if self.rr_choices:
            individual["rr"] = self.rng.choice(self.rr_choices)
        return individual

    def initial_population(self) -> list[dict]:
        return [self._random_individual() for _ in range(self.population_size)]

    def next_population(self, scored_population: list[tuple[float, dict]]) -> list[dict]:
        ranked = sorted(scored_population, key=lambda pair: pair[0], reverse=True)
        next_gen = [copy.deepcopy(individual) for _, individual in ranked[: self.elite_count]]

        while len(next_gen) < self.population_size:
            parent_a = _tournament_select(scored_population, self.rng)
            parent_b = _tournament_select(scored_population, self.rng)
            child = _crossover(parent_a, parent_b, self.rng, self.max_leaves, self.max_depth)
            child = _mutate(
                child, self.rng, self.grouped, self.pool, self.mutation_rate,
                self.mtf_timeframes, self.mtf_probability, self.rr_choices,
                self.allowed_param_values, self.allowed_literal_values, self.allowed_directions,
            )
            next_gen.append(child)

        return next_gen

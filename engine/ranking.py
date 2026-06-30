from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class RankingWeights:
    profit_factor: float = 30.0
    net_profit: float = 20.0
    max_dd: float = 15.0
    win_rate: float = 10.0
    expected_value: float = 10.0
    year_stability: float = 10.0
    month_stability: float = 5.0
    walk_forward_score: float = 20.0


@dataclass
class RankingFilter:
    min_trades: int = 0
    min_profit_factor: float = 0.0
    min_net_profit: float = -float("inf")
    max_dd: float = float("inf")
    min_win_rate: float = 0.0
    min_expected_value: float = -float("inf")
    min_year_stability: float = 0.0
    min_month_stability: float = 0.0
    min_walk_forward_score: float = 0.0


@dataclass
class RankingConfig:
    weights: RankingWeights = field(default_factory=RankingWeights)
    filters: RankingFilter = field(default_factory=RankingFilter)
    top_n: int | None = None


def rank_results(
    results_df: pd.DataFrame,
    config: RankingConfig | None = None,
) -> pd.DataFrame:
    if config is None:
        config = RankingConfig()

    if results_df is None or results_df.empty:
        return pd.DataFrame()

    df = results_df.copy()
    df = ensure_ranking_columns(df)

    df = apply_ranking_filter(df, config.filters)

    if df.empty:
        return df

    df["rank_score"] = calc_rank_score(df, config.weights)

    df = df.sort_values(
        by=[
            "rank_score",
            "profit_factor",
            "net_profit",
            "year_stability",
            "month_stability",
            "win_rate",
        ],
        ascending=[False, False, False, False, False, False],
    ).reset_index(drop=True)

    df.insert(0, "rank", np.arange(1, len(df) + 1))

    if config.top_n is not None and config.top_n > 0:
        df = df.head(config.top_n).reset_index(drop=True)

    return df


def ensure_ranking_columns(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()

    alias_map = {
        "profit": "net_profit",
        "total_profit": "net_profit",
        "pf": "profit_factor",
        "winrate": "win_rate",
        "trade_count": "trades",
        "total_trades": "trades",
        "max_drawdown": "max_dd",
        "ev": "expected_value",
        "wf_score": "walk_forward_score",
    }

    for old_col, new_col in alias_map.items():
        if old_col in work.columns and new_col not in work.columns:
            work[new_col] = work[old_col]

    defaults: dict[str, Any] = {
        "param_id": "",
        "net_profit": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "profit_factor": 0.0,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "avg_profit": 0.0,
        "expected_value": 0.0,
        "max_dd": 0.0,
        "max_win_streak": 0,
        "max_loss_streak": 0,
        "year_stability": 0.0,
        "month_stability": 0.0,
        "walk_forward_score": 0.0,
    }

    for col, default in defaults.items():
        if col not in work.columns:
            work[col] = default

    numeric_cols = [
        "net_profit",
        "gross_profit",
        "gross_loss",
        "profit_factor",
        "trades",
        "wins",
        "losses",
        "win_rate",
        "avg_profit",
        "expected_value",
        "max_dd",
        "max_win_streak",
        "max_loss_streak",
        "year_stability",
        "month_stability",
        "walk_forward_score",
    ]

    for col in numeric_cols:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    work["profit_factor"] = work["profit_factor"].replace([np.inf, -np.inf], np.nan)
    work["profit_factor"] = work["profit_factor"].fillna(work["profit_factor"].max())

    for col in numeric_cols:
        if work[col].isna().all():
            work[col] = defaults[col]
        else:
            work[col] = work[col].fillna(defaults[col])

    return work


def apply_ranking_filter(
    df: pd.DataFrame,
    filters: RankingFilter,
) -> pd.DataFrame:
    work = df.copy()

    work = work[work["trades"] >= filters.min_trades]
    work = work[work["profit_factor"] >= filters.min_profit_factor]
    work = work[work["net_profit"] >= filters.min_net_profit]
    work = work[work["max_dd"] <= filters.max_dd]
    work = work[work["win_rate"] >= filters.min_win_rate]
    work = work[work["expected_value"] >= filters.min_expected_value]
    work = work[work["year_stability"] >= filters.min_year_stability]
    work = work[work["month_stability"] >= filters.min_month_stability]
    work = work[work["walk_forward_score"] >= filters.min_walk_forward_score]

    return work.reset_index(drop=True)


def calc_rank_score(
    df: pd.DataFrame,
    weights: RankingWeights,
) -> pd.Series:
    pf_score = normalize_higher_better(df["profit_factor"])
    profit_score = normalize_higher_better(df["net_profit"])
    win_rate_score = normalize_higher_better(df["win_rate"])
    ev_score = normalize_higher_better(df["expected_value"])
    year_stability_score = normalize_higher_better(df["year_stability"])
    month_stability_score = normalize_higher_better(df["month_stability"])
    wf_score = normalize_higher_better(df["walk_forward_score"])

    dd_score = normalize_lower_better(df["max_dd"])

    score = (
        pf_score * weights.profit_factor
        + profit_score * weights.net_profit
        + dd_score * weights.max_dd
        + win_rate_score * weights.win_rate
        + ev_score * weights.expected_value
        + year_stability_score * weights.year_stability
        + month_stability_score * weights.month_stability
        + wf_score * weights.walk_forward_score
    )

    return score.round(10)


def normalize_higher_better(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)

    if s.isna().all():
        return pd.Series(np.zeros(len(series)), index=series.index)

    s = s.fillna(s.min())

    min_v = float(s.min())
    max_v = float(s.max())

    if max_v == min_v:
        return pd.Series(np.ones(len(series)), index=series.index)

    return (s - min_v) / (max_v - min_v)


def normalize_lower_better(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)

    if s.isna().all():
        return pd.Series(np.zeros(len(series)), index=series.index)

    s = s.fillna(s.max())

    min_v = float(s.min())
    max_v = float(s.max())

    if max_v == min_v:
        return pd.Series(np.ones(len(series)), index=series.index)

    return 1.0 - ((s - min_v) / (max_v - min_v))


def sort_by_profit_factor(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["profit_factor", "net_profit", "trades"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def sort_by_drawdown(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["max_dd", "profit_factor", "net_profit"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def sort_by_win_rate(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["win_rate", "profit_factor", "net_profit"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def sort_by_profit(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["net_profit", "profit_factor", "max_dd"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def sort_by_expected_value(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["expected_value", "profit_factor", "net_profit"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def sort_by_year_stability(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["year_stability", "profit_factor", "net_profit"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def sort_by_month_stability(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["month_stability", "profit_factor", "net_profit"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def sort_by_walk_forward_score(df: pd.DataFrame) -> pd.DataFrame:
    work = ensure_ranking_columns(df)
    return work.sort_values(
        by=["walk_forward_score", "profit_factor", "net_profit"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def export_rankings(
    df: pd.DataFrame,
    output_dir: str,
    prefix: str = "ranking",
) -> dict[str, str]:
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    rankings = {
        "total": rank_results(df),
        "pf": sort_by_profit_factor(df),
        "dd": sort_by_drawdown(df),
        "win_rate": sort_by_win_rate(df),
        "profit": sort_by_profit(df),
        "expected_value": sort_by_expected_value(df),
        "year_stability": sort_by_year_stability(df),
        "month_stability": sort_by_month_stability(df),
        "walk_forward": sort_by_walk_forward_score(df),
    }

    paths: dict[str, str] = {}

    for name, ranking_df in rankings.items():
        path = output_path / f"{prefix}_{name}.csv"
        ranking_df.to_csv(path, index=False, encoding="utf-8-sig")
        paths[name] = str(path)

    return paths


def load_ranking_weights_from_csv(path: str) -> RankingWeights:
    df = pd.read_csv(path)

    if "name" not in df.columns or "weight" not in df.columns:
        raise ValueError("weights csv must have columns: name, weight")

    values = {
        str(row["name"]): float(row["weight"])
        for _, row in df.iterrows()
    }

    return RankingWeights(
        profit_factor=values.get("profit_factor", 30.0),
        net_profit=values.get("net_profit", 20.0),
        max_dd=values.get("max_dd", 15.0),
        win_rate=values.get("win_rate", 10.0),
        expected_value=values.get("expected_value", 10.0),
        year_stability=values.get("year_stability", 10.0),
        month_stability=values.get("month_stability", 5.0),
        walk_forward_score=values.get("walk_forward_score", 20.0),
    )


def save_default_ranking_weights_csv(path: str) -> None:
    weights = RankingWeights()

    df = pd.DataFrame(
        [
            {"name": "profit_factor", "weight": weights.profit_factor},
            {"name": "net_profit", "weight": weights.net_profit},
            {"name": "max_dd", "weight": weights.max_dd},
            {"name": "win_rate", "weight": weights.win_rate},
            {"name": "expected_value", "weight": weights.expected_value},
            {"name": "year_stability", "weight": weights.year_stability},
            {"name": "month_stability", "weight": weights.month_stability},
            {"name": "walk_forward_score", "weight": weights.walk_forward_score},
        ]
    )

    df.to_csv(path, index=False, encoding="utf-8-sig")
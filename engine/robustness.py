"""Combine independent robustness signals into one Confidence Score (V3.0).

Rather than inventing a new statistic from scratch, this reuses the three
A-D letter grades the pipeline already produces independently (stability,
Monte Carlo, walk-forward) plus the new parameter-sensitivity grade, and
averages them. Each of those grades is already a considered judgment about
one specific failure mode (inconsistent yearly/monthly returns, drawdown
tail risk, out-of-sample decay, overfitting to one parameter value) - this
just says "how many of those independent checks look good."

walk_forward_summary.csv and sensitivity_summary.csv are produced by
separate manual tools (walk_forward.py + analyze_walk_forward.py,
analyze_sensitivity.py), not by main.py itself, and main.py overwrites
output/ on every run. That means these two files can be stale - left over
from a *different* best-parameter run than the one currently in
output/ranking_total.csv. This module doesn't try to detect that (there's
no run identifier tying them together); it's on the caller to have
re-run walk_forward.py/analyze_sensitivity.py against the current best
result before trusting the combined score. See analyze_confidence.py's
printed warning.
"""

from pathlib import Path

import pandas as pd

RATING_TO_SCORE = {"A": 100.0, "B": 75.0, "C": 50.0, "D": 25.0}


def _score_to_rating(score: float) -> str:
    if score >= 87.5:
        return "A"
    if score >= 62.5:
        return "B"
    if score >= 37.5:
        return "C"
    return "D"


def load_stability_component(output_dir: Path) -> dict | None:
    path = output_dir / "stability_analysis.csv"
    if not path.exists():
        return None

    row = pd.read_csv(path).iloc[0]
    return {"name": "stability", "rating": str(row["rating"]), "score": float(row["overall_stability_score"])}


def load_monte_carlo_component(output_dir: Path) -> dict | None:
    path = output_dir / "monte_carlo_summary.csv"
    if not path.exists():
        return None

    row = pd.read_csv(path).iloc[0]
    return {"name": "monte_carlo", "rating": str(row["rating"]), "score": None}


def load_walk_forward_component(output_dir: Path) -> dict | None:
    path = output_dir / "walk_forward_summary.csv"
    if not path.exists():
        return None

    row = pd.read_csv(path).iloc[0]
    return {"name": "walk_forward", "rating": str(row["overall_rating"]), "score": float(row["pass_rate"])}


def load_sensitivity_component(output_dir: Path) -> dict | None:
    path = output_dir / "sensitivity_summary.csv"
    if not path.exists():
        return None

    row = pd.read_csv(path).iloc[0]
    return {"name": "sensitivity", "rating": str(row["sensitivity_rating"]), "score": float(row["sensitivity_score"])}


def compute_confidence_score(output_dir: Path) -> dict:
    loaders = [
        load_stability_component,
        load_monte_carlo_component,
        load_walk_forward_component,
        load_sensitivity_component,
    ]

    components = [loader(output_dir) for loader in loaders]
    available = [component for component in components if component is not None]

    if not available:
        return {
            "confidence_score": 0.0,
            "confidence_rating": "N/A",
            "components_used": [],
            "components_missing": [component.__name__ for component in loaders],
        }

    letter_scores = [RATING_TO_SCORE.get(component["rating"], 0.0) for component in available]
    confidence_score = round(sum(letter_scores) / len(letter_scores), 2)

    return {
        "confidence_score": confidence_score,
        "confidence_rating": _score_to_rating(confidence_score),
        "components_used": [
            {"name": component["name"], "rating": component["rating"]} for component in available
        ],
        "components_missing": [
            loader.__name__.replace("load_", "").replace("_component", "")
            for loader, component in zip(loaders, components)
            if component is None
        ],
    }

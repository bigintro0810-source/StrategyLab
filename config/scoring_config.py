from dataclasses import dataclass
from pathlib import Path
import csv


@dataclass(frozen=True)
class ScoringConfig:
    pf_weight: float = 1000.0
    profit_weight: float = 2.0
    expectancy_weight: float = 10000.0
    win_rate_weight: float = 10.0
    drawdown_weight: float = 50.0
    trades_weight: float = 0.0

    yearly_stability_weight: float = 20.0
    winning_years_weight: float = 30.0
    losing_years_weight: float = 50.0
    avg_yearly_profit_weight: float = 5.0
    min_yearly_profit_weight: float = 5.0

    monthly_stability_weight: float = 20.0
    winning_months_weight: float = 2.0
    losing_months_weight: float = 2.0
    avg_monthly_profit_weight: float = 10.0
    min_monthly_profit_weight: float = 10.0

    max_consecutive_wins_weight: float = 0.0
    max_consecutive_losses_weight: float = 20.0

    minimum_trades: int = 1000
    minimum_profit: float = 0.0
    minimum_pf: float = 1.05
    minimum_yearly_stability: float = 0.0

    maximum_drawdown: float = 999999.0
    minimum_win_rate: float = 0.0
    minimum_average_profit: float = -999999.0

    minimum_monthly_stability: float = 0.0
    maximum_consecutive_losses: int = 999999

    exclude_long: int = 0
    exclude_short: int = 0

    only_session: str = ""


def load_scoring_config(path="config/scoring_weights.csv") -> ScoringConfig:
    config_path = Path(path)
    default = ScoringConfig()

    if not config_path.exists():
        return default

    values = {}

    with config_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            key = row.get("key")
            value = row.get("value")

            if key is None or value is None:
                continue

            key = key.strip()
            value = value.strip()

            if not hasattr(default, key):
                continue

            current_value = getattr(default, key)

            if isinstance(current_value, int):
                values[key] = int(float(value)) if value != "" else current_value
            elif isinstance(current_value, str):
                values[key] = value
            else:
                values[key] = float(value) if value != "" else current_value

    return ScoringConfig(**{
        **default.__dict__,
        **values,
    })
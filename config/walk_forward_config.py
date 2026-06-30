from dataclasses import dataclass


@dataclass(frozen=True)
class WalkForwardConfig:
    train_years: int = 10
    test_years: int = 2

    start_year: int = 2003
    end_year: int = 2026

    top_n: int = 10

    minimum_train_trades: int = 1000
    minimum_test_trades: int = 100

    minimum_train_pf: float = 1.05
    minimum_test_pf: float = 1.00
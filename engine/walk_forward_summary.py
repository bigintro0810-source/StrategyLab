from dataclasses import dataclass

from engine.walk_forward_result import WalkForwardResult


@dataclass
class WalkForwardSummary:
    total_windows: int
    passed_windows: int

    pass_rate: float

    average_pf: float
    average_profit: float
    average_drawdown: float

    def to_dict(self):
        return {
            "total_windows": self.total_windows,
            "passed_windows": self.passed_windows,
            "pass_rate": self.pass_rate,
            "average_pf": self.average_pf,
            "average_profit": self.average_profit,
            "average_drawdown": self.average_drawdown,
        }


def summarize(results: list[WalkForwardResult]):

    if len(results) == 0:
        return WalkForwardSummary(
            0,
            0,
            0.0,
            0.0,
            0.0,
            0.0,
        )

    passed = sum(r.passed for r in results)

    avg_pf = sum(r.profit_factor for r in results) / len(results)
    avg_profit = sum(r.total_profit for r in results) / len(results)
    avg_dd = sum(r.max_drawdown for r in results) / len(results)

    return WalkForwardSummary(
        total_windows=len(results),
        passed_windows=passed,
        pass_rate=passed / len(results) * 100,
        average_pf=avg_pf,
        average_profit=avg_profit,
        average_drawdown=avg_dd,
    )
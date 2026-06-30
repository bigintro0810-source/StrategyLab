from engine.walk_forward_result import WalkForwardResult


class WalkForwardEngine:

    def evaluate(
        self,
        train_start,
        train_end,
        test_start,
        test_end,
        result,
    ):
        passed = (
            result.profit_factor >= 1.0
            and result.total_profit > 0
            and result.max_drawdown <= 20
        )

        return WalkForwardResult(
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            score=result.score,
            profit_factor=result.profit_factor,
            total_profit=result.total_profit,
            max_drawdown=result.max_drawdown,
            win_rate=result.win_rate,
            yearly_stability=result.yearly_stability,
            monthly_stability=result.monthly_stability,
            max_consecutive_wins=result.max_consecutive_wins,
            max_consecutive_losses=result.max_consecutive_losses,
            passed=passed,
        )
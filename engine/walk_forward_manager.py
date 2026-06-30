from engine.walk_forward_runner import WalkForwardRunner


class WalkForwardManager:

    def __init__(self):
        self.runner = WalkForwardRunner()

    def execute(self, plans, results):

        summary, output_path = self.runner.run(
            plans,
            results,
        )

        print()
        print("========== Walk Forward Summary ==========")
        print()

        print(f"対象期間       : {summary.total_windows}")
        print(f"合格期間       : {summary.passed_windows}")
        print(f"合格率         : {summary.pass_rate:.2f}%")
        print(f"平均PF         : {summary.average_pf:.2f}")
        print(f"平均利益       : {summary.average_profit:.2f}")
        print(f"平均DD         : {summary.average_drawdown:.2f}")

        print()
        print("CSV保存完了")
        print(output_path)

        return summary
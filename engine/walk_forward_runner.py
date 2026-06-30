from engine.walk_forward_engine import WalkForwardEngine
from engine.walk_forward_summary import summarize
from engine.walk_forward_exporter import WalkForwardExporter


class WalkForwardRunner:

    def __init__(self):
        self.engine = WalkForwardEngine()
        self.exporter = WalkForwardExporter()

    def run(self, plans, results):

        walk_results = []

        for plan, result in zip(plans, results):

            walk_result = self.engine.evaluate(
                train_start=plan["train_start"],
                train_end=plan["train_end"],
                test_start=plan["test_start"],
                test_end=plan["test_end"],
                result=result,
            )

            walk_results.append(walk_result)

        summary = summarize(walk_results)

        output_path = self.exporter.export(walk_results)

        return summary, output_path
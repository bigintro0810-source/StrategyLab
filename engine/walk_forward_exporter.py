from pathlib import Path

import pandas as pd

from engine.walk_forward_result import WalkForwardResult


class WalkForwardExporter:

    def __init__(self, output_dir="output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def export(
        self,
        results: list[WalkForwardResult],
        filename="walk_forward_results.csv",
    ):
        df = pd.DataFrame([r.to_dict() for r in results])

        path = self.output_dir / filename

        df.to_csv(path, index=False)

        return path
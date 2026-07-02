from pathlib import Path

import pandas as pd

from engine.html_report import REPORT_CSS, build_multi_equity_curve_svg
from engine.strategy_registry import get_strategy

COMPARISON_OUTPUT = Path("saved_strategies") / "comparison.html"


def _load_equity_series(entry: dict) -> list[float]:
    equity_path = Path(entry["snapshot_dir"]) / "equity_curve.csv"

    if not equity_path.exists():
        return []

    return pd.read_csv(equity_path)["equity"].tolist()


def build_metrics_table(entries: list[dict]) -> str:
    rows = []
    for entry in entries:
        rows.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "mode": entry["mode"],
                "timeframe": entry["timeframe"],
                "favorite": "★" if entry["favorite"] else "",
                "tags": ", ".join(entry["tags"]),
                **entry["metrics"],
            }
        )

    return pd.DataFrame(rows).to_html(index=False, classes="ranking")


def build_comparison_html(entries: list[dict]) -> str:
    metrics_table = (
        build_metrics_table(entries) if entries else "<p>データがありません。</p>"
    )

    series = {entry["name"]: _load_equity_series(entry) for entry in entries}
    equity_chart = build_multi_equity_curve_svg(series)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>Strategy Lab 戦略比較レポート</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<h1>Strategy Lab 戦略比較レポート</h1>
<p>比較対象: {len(entries)}件</p>

<h2>指標比較</h2>
{metrics_table}

<h2>Equity Curve比較（トレード進捗率で正規化）</h2>
<div class="chart-wrap">{equity_chart}</div>

</body>
</html>
"""


def export_comparison_report(strategy_ids: list[str]) -> Path:
    entries = [get_strategy(strategy_id) for strategy_id in strategy_ids]
    html = build_comparison_html(entries)

    COMPARISON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    COMPARISON_OUTPUT.write_text(html, encoding="utf-8")

    return COMPARISON_OUTPUT

from pathlib import Path

import pandas as pd


REPORT_CSS = """
body { font-family: -apple-system, "Segoe UI", "Yu Gothic", sans-serif; margin: 24px; color: #1a1a1a; }
h1, h2 { border-bottom: 2px solid #333; padding-bottom: 4px; }
table { border-collapse: collapse; margin-bottom: 24px; width: 100%; }
th, td { border: 1px solid #ccc; padding: 4px 8px; font-size: 13px; }
th { background: #f0f0f0; }
table.heatmap td { padding: 6px 12px; }
.summary { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
.summary div { background: #f7f7f7; border: 1px solid #ddd; border-radius: 6px; padding: 12px 16px; min-width: 100px; }
.summary .label { font-size: 12px; color: #666; }
.summary .value { font-size: 20px; font-weight: bold; }
.chart-wrap { margin-bottom: 24px; }
.chart-wrap svg { border: 1px solid #ddd; border-radius: 6px; background: #fff; }
.legend { margin-bottom: 8px; font-size: 13px; }
"""

MULTI_SERIES_COLORS = [
    "#2e8b3f", "#c0392b", "#2b7cd3", "#e67e22",
    "#8e44ad", "#16a085", "#d4ac0d", "#7f8c8d",
]

CHART_WIDTH = 880
CHART_HEIGHT = 240
CHART_PAD_LEFT = 60
CHART_PAD_RIGHT = 20
CHART_PAD_TOP = 20
CHART_PAD_BOTTOM = 30


def _color_for_value(value: float, vmin: float, vmax: float) -> str:
    if value >= 0:
        ratio = value / vmax if vmax > 0 else 0.0
        ratio = max(0.0, min(ratio, 1.0))
        r = int(255 - 155 * ratio)
        g = 255
        b = int(255 - 155 * ratio)
    else:
        ratio = value / vmin if vmin < 0 else 0.0
        ratio = max(0.0, min(ratio, 1.0))
        r = 255
        g = int(255 - 155 * ratio)
        b = int(255 - 155 * ratio)

    return f"rgb({r},{g},{b})"


def build_heatmap_html(df: pd.DataFrame, value_col: str, label_col: str) -> str:
    if df.empty:
        return "<p>データがありません。</p>"

    vmax = float(df[value_col].max())
    vmin = float(df[value_col].min())

    # df.iterrows() upcasts every column in a row to a shared dtype (e.g. int
    # year -> 2003.0), so iterate the label/value columns separately instead.
    labels = df[label_col].tolist()
    values = df[value_col].tolist()

    rows = []
    for label, value in zip(labels, values):
        color = _color_for_value(float(value), vmin, vmax)
        rows.append(
            f"<tr><td>{label}</td>"
            f'<td style="background-color:{color}; text-align:right;">'
            f"{float(value):.4f}</td></tr>"
        )

    return (
        '<table class="heatmap">'
        f"<thead><tr><th>{label_col}</th><th>{value_col}</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _scale_points(values: list[float]) -> tuple[list[tuple[float, float]], float, float]:
    plot_w = CHART_WIDTH - CHART_PAD_LEFT - CHART_PAD_RIGHT
    plot_h = CHART_HEIGHT - CHART_PAD_TOP - CHART_PAD_BOTTOM

    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        vmax = vmin + 1.0

    n = len(values)
    points = []
    for i, value in enumerate(values):
        x = CHART_PAD_LEFT + (i / (n - 1) if n > 1 else 0.0) * plot_w
        y = CHART_PAD_TOP + (1 - (value - vmin) / (vmax - vmin)) * plot_h
        points.append((x, y))

    return points, vmin, vmax


def _value_to_y(value: float, vmin: float, vmax: float) -> float:
    plot_h = CHART_HEIGHT - CHART_PAD_TOP - CHART_PAD_BOTTOM
    return CHART_PAD_TOP + (1 - (value - vmin) / (vmax - vmin)) * plot_h


def build_equity_curve_svg(equity_df: pd.DataFrame) -> str:
    if equity_df.empty:
        return "<p>データがありません。</p>"

    values = equity_df["equity"].tolist()
    trade_numbers = equity_df["trade_number"].tolist()
    points, vmin, vmax = _scale_points(values)

    line_color = "#2e8b3f" if values[-1] >= 0 else "#c0392b"
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    zero_line = ""
    if vmin < 0 < vmax:
        zero_y = _value_to_y(0.0, vmin, vmax)
        zero_line = (
            f'<line x1="{CHART_PAD_LEFT}" y1="{zero_y:.1f}" '
            f'x2="{CHART_WIDTH - CHART_PAD_RIGHT}" y2="{zero_y:.1f}" '
            f'stroke="#999" stroke-dasharray="4,4" />'
        )

    return (
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" xmlns="http://www.w3.org/2000/svg">'
        f'<text x="{CHART_PAD_LEFT - 8}" y="{CHART_PAD_TOP}" text-anchor="end" font-size="11">{vmax:.2f}</text>'
        f'<text x="{CHART_PAD_LEFT - 8}" y="{CHART_HEIGHT - CHART_PAD_BOTTOM}" text-anchor="end" font-size="11">{vmin:.2f}</text>'
        f'<text x="{CHART_PAD_LEFT}" y="{CHART_HEIGHT - 8}" font-size="11">{trade_numbers[0]}</text>'
        f'<text x="{CHART_WIDTH - CHART_PAD_RIGHT}" y="{CHART_HEIGHT - 8}" text-anchor="end" font-size="11">{trade_numbers[-1]}</text>'
        f"{zero_line}"
        f'<polyline points="{polyline}" fill="none" stroke="{line_color}" stroke-width="1.5" />'
        "</svg>"
    )


def build_drawdown_curve_svg(equity_df: pd.DataFrame) -> str:
    if equity_df.empty:
        return "<p>データがありません。</p>"

    values = [-v for v in equity_df["drawdown"].tolist()]
    trade_numbers = equity_df["trade_number"].tolist()
    points, vmin, vmax = _scale_points(values)

    zero_y = _value_to_y(0.0, vmin, vmax)
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area_points = (
        f"{CHART_PAD_LEFT:.1f},{zero_y:.1f} {polyline} "
        f"{points[-1][0]:.1f},{zero_y:.1f}"
    )

    return (
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" xmlns="http://www.w3.org/2000/svg">'
        f'<text x="{CHART_PAD_LEFT - 8}" y="{CHART_PAD_TOP}" text-anchor="end" font-size="11">0</text>'
        f'<text x="{CHART_PAD_LEFT - 8}" y="{CHART_HEIGHT - CHART_PAD_BOTTOM}" text-anchor="end" font-size="11">{-vmin:.2f}</text>'
        f'<text x="{CHART_PAD_LEFT}" y="{CHART_HEIGHT - 8}" font-size="11">{trade_numbers[0]}</text>'
        f'<text x="{CHART_WIDTH - CHART_PAD_RIGHT}" y="{CHART_HEIGHT - 8}" text-anchor="end" font-size="11">{trade_numbers[-1]}</text>'
        f'<polygon points="{area_points}" fill="#c0392b" fill-opacity="0.25" stroke="none" />'
        f'<polyline points="{polyline}" fill="none" stroke="#c0392b" stroke-width="1.5" />'
        "</svg>"
    )


def build_multi_equity_curve_svg(series: dict[str, list[float]]) -> str:
    series = {label: values for label, values in series.items() if values}
    if not series:
        return "<p>データがありません。</p>"

    all_values = [v for values in series.values() for v in values]
    vmin = min(all_values)
    vmax = max(all_values)
    if vmax == vmin:
        vmax = vmin + 1.0

    plot_w = CHART_WIDTH - CHART_PAD_LEFT - CHART_PAD_RIGHT

    lines = []
    legend_items = []
    for i, (label, values) in enumerate(series.items()):
        color = MULTI_SERIES_COLORS[i % len(MULTI_SERIES_COLORS)]
        n = len(values)
        points = []
        for idx, value in enumerate(values):
            x = CHART_PAD_LEFT + (idx / (n - 1) if n > 1 else 0.0) * plot_w
            y = _value_to_y(value, vmin, vmax)
            points.append(f"{x:.1f},{y:.1f}")
        lines.append(
            f'<polyline points="{" ".join(points)}" '
            f'fill="none" stroke="{color}" stroke-width="1.5" />'
        )
        legend_items.append((label, color))

    zero_line = ""
    if vmin < 0 < vmax:
        zero_y = _value_to_y(0.0, vmin, vmax)
        zero_line = (
            f'<line x1="{CHART_PAD_LEFT}" y1="{zero_y:.1f}" '
            f'x2="{CHART_WIDTH - CHART_PAD_RIGHT}" y2="{zero_y:.1f}" '
            f'stroke="#999" stroke-dasharray="4,4" />'
        )

    legend_html = "".join(
        f'<span style="color:{color}; margin-right:16px;">■ {label}</span>'
        for label, color in legend_items
    )

    svg = (
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" xmlns="http://www.w3.org/2000/svg">'
        f'<text x="{CHART_PAD_LEFT - 8}" y="{CHART_PAD_TOP}" text-anchor="end" font-size="11">{vmax:.2f}</text>'
        f'<text x="{CHART_PAD_LEFT - 8}" y="{CHART_HEIGHT - CHART_PAD_BOTTOM}" text-anchor="end" font-size="11">{vmin:.2f}</text>'
        f'<text x="{CHART_PAD_LEFT}" y="{CHART_HEIGHT - 8}" font-size="11">0%</text>'
        f'<text x="{CHART_WIDTH - CHART_PAD_RIGHT}" y="{CHART_HEIGHT - 8}" text-anchor="end" font-size="11">100%</text>'
        f"{zero_line}"
        f"{''.join(lines)}"
        "</svg>"
    )

    return f'<div class="legend">{legend_html}</div>{svg}'


def build_summary_cards(
    best_row: pd.Series | None,
    stability_row: pd.Series | None,
    monte_carlo_row: pd.Series | None,
) -> str:
    cards: list[tuple[str, str]] = []

    if best_row is not None:
        cards.append(("純利益", f"{best_row['net_profit']:.4f}"))
        cards.append(("PF", f"{best_row['profit_factor']:.3f}"))
        cards.append(("最大DD", f"{best_row['max_dd']:.4f}"))
        cards.append(("勝率", f"{best_row['win_rate']:.2f}%"))
        cards.append(("トレード数", f"{int(best_row['trades'])}"))

        if "recovery_factor" in best_row:
            cards.append(("Recovery Factor", f"{best_row['recovery_factor']:.3f}"))

    if stability_row is not None:
        cards.append(
            (
                "総合安定度",
                f"{stability_row['overall_stability_score']} ({stability_row['rating']})",
            )
        )

    if monte_carlo_row is not None:
        cards.append(("Monte Carlo評価", f"{monte_carlo_row['rating']}"))

    return "".join(
        f'<div><div class="label">{label}</div><div class="value">{value}</div></div>'
        for label, value in cards
    )


def build_html_report(
    mode: str,
    timeframe: str,
    ranking_total: pd.DataFrame,
    yearly_df: pd.DataFrame,
    monthly_df: pd.DataFrame,
    stability_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    monte_carlo_summary: pd.DataFrame,
) -> str:
    best_row = ranking_total.iloc[0] if not ranking_total.empty else None
    stability_row = stability_df.iloc[0] if not stability_df.empty else None
    monte_carlo_row = monte_carlo_summary.iloc[0] if not monte_carlo_summary.empty else None

    summary_html = build_summary_cards(best_row, stability_row, monte_carlo_row)

    ranking_table = (
        ranking_total.head(20).to_html(index=False, classes="ranking")
        if not ranking_total.empty
        else "<p>データがありません。</p>"
    )

    equity_curve_svg = build_equity_curve_svg(equity_df)
    drawdown_curve_svg = build_drawdown_curve_svg(equity_df)
    yearly_heatmap = build_heatmap_html(yearly_df, "net_profit", "year")
    monthly_heatmap = build_heatmap_html(monthly_df, "net_profit", "year_month")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>Strategy Lab レポート</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<h1>Strategy Lab レポート</h1>
<p>モード: {mode} / 時間足: {timeframe}</p>

<h2>サマリー</h2>
<div class="summary">{summary_html}</div>

<h2>総合ランキング 上位20件</h2>
{ranking_table}

<h2>Equity Curve</h2>
<div class="chart-wrap">{equity_curve_svg}</div>

<h2>Drawdown Curve</h2>
<div class="chart-wrap">{drawdown_curve_svg}</div>

<h2>年別損益ヒートマップ</h2>
{yearly_heatmap}

<h2>月別損益ヒートマップ</h2>
{monthly_heatmap}

</body>
</html>
"""


def export_html_report(
    output_dir: Path,
    mode: str,
    timeframe: str,
    ranking_total: pd.DataFrame,
    yearly_df: pd.DataFrame,
    monthly_df: pd.DataFrame,
    stability_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    monte_carlo_summary: pd.DataFrame,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    html = build_html_report(
        mode=mode,
        timeframe=timeframe,
        ranking_total=ranking_total,
        yearly_df=yearly_df,
        monthly_df=monthly_df,
        stability_df=stability_df,
        equity_df=equity_df,
        monte_carlo_summary=monte_carlo_summary,
    )

    output_path = output_dir / "report.html"
    output_path.write_text(html, encoding="utf-8")

    return output_path

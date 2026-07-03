"""PDF export of the strategy report (V4.0 PDF/Excel出力).

Deliberately does NOT convert report.html to PDF (weasyprint needs
system-level GTK+/Pango/Cairo libraries that are painful to install
reliably on Windows; playwright/headless-Chromium needs a ~200MB browser
download beyond pip; xhtml2pdf has poor/no SVG support, which would break
the equity/drawdown charts). Instead this redraws a summary report
natively with fpdf2 (pure Python, no system dependencies) - fewer
features than the HTML report, but reliable to install and render.

Uses a bundled Windows Japanese font (Yu Gothic) so labels can stay in
Japanese, matching engine/html_report.py's language. Falls back to
Helvetica (no Japanese support) if the font file isn't found, rather than
failing outright - PDF export is a nice-to-have, not something that
should block the rest of the pipeline finishing.
"""

from pathlib import Path

import pandas as pd
from fpdf import FPDF

JP_FONT_CANDIDATES = [
    "C:/Windows/Fonts/YuGothR.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]

CHART_WIDTH_MM = 170
CHART_HEIGHT_MM = 50


def _find_japanese_font() -> str | None:
    for candidate in JP_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.jp_font_path = _find_japanese_font()

        if self.jp_font_path:
            self.add_font("JP", "", self.jp_font_path)
            self.font_name = "JP"
        else:
            self.font_name = "Helvetica"

    def h1(self, text: str) -> None:
        self.set_font(self.font_name, size=18)
        self.cell(0, 12, text, new_x="LMARGIN", new_y="NEXT")

    def h2(self, text: str) -> None:
        self.ln(4)
        self.set_font(self.font_name, size=13)
        self.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")

    def body(self, text: str) -> None:
        self.set_font(self.font_name, size=10)
        self.cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")


def _draw_line_chart(
    pdf: ReportPDF,
    values: list[float],
    color: tuple[int, int, int],
    zero_line: bool = False,
) -> None:
    if not values:
        pdf.body("データがありません。")
        return

    x0 = pdf.get_x()
    y0 = pdf.get_y()

    pdf.set_draw_color(200, 200, 200)
    pdf.rect(x0, y0, CHART_WIDTH_MM, CHART_HEIGHT_MM)

    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        vmax = vmin + 1.0

    n = len(values)

    def to_xy(index: int, value: float) -> tuple[float, float]:
        x = x0 + (index / (n - 1) if n > 1 else 0.0) * CHART_WIDTH_MM
        y = y0 + (1 - (value - vmin) / (vmax - vmin)) * CHART_HEIGHT_MM
        return x, y

    if zero_line and vmin < 0 < vmax:
        _, zy = to_xy(0, 0.0)
        pdf.set_draw_color(180, 180, 180)
        pdf.line(x0, zy, x0 + CHART_WIDTH_MM, zy)

    pdf.set_draw_color(*color)
    prev_xy = None
    for i, value in enumerate(values):
        xy = to_xy(i, value)
        if prev_xy is not None:
            pdf.line(prev_xy[0], prev_xy[1], xy[0], xy[1])
        prev_xy = xy

    pdf.set_xy(x0, y0 + CHART_HEIGHT_MM + 4)
    pdf.set_font(pdf.font_name, size=8)
    pdf.cell(0, 5, f"min: {vmin:.3f}  /  max: {vmax:.3f}", new_x="LMARGIN", new_y="NEXT")


def _draw_table(pdf: ReportPDF, df: pd.DataFrame, columns: list[str], max_rows: int = 15) -> None:
    if df.empty:
        pdf.body("データがありません。")
        return

    display_df = df[columns].head(max_rows)
    col_width = (CHART_WIDTH_MM) / len(columns)

    pdf.set_font(pdf.font_name, size=8)
    for col in columns:
        pdf.cell(col_width, 7, str(col), border=1)
    pdf.ln(7)

    int_like_columns = {"rank", "trades"}

    for _, row in display_df.iterrows():
        for col in columns:
            value = row[col]
            if col in int_like_columns:
                text = str(int(value))
            elif isinstance(value, float):
                text = f"{value:.4f}"
            else:
                text = str(value)
            pdf.cell(col_width, 6, text, border=1)
        pdf.ln(6)


def build_pdf_report(
    mode: str,
    timeframe: str,
    symbol: str,
    ranking_total: pd.DataFrame,
    equity_df: pd.DataFrame,
    stability_df: pd.DataFrame,
    monte_carlo_summary: pd.DataFrame,
) -> ReportPDF:
    pdf = ReportPDF()
    pdf.add_page()

    pdf.h1("Strategy Lab レポート")
    pdf.body(f"通貨ペア: {symbol}  /  モード: {mode}  /  時間足: {timeframe}")

    best_row = ranking_total.iloc[0] if not ranking_total.empty else None

    if best_row is not None:
        pdf.h2("サマリー")
        pdf.body(f"純利益: {best_row['net_profit']:.4f}    PF: {best_row['profit_factor']:.3f}")
        pdf.body(f"最大DD: {best_row['max_dd']:.4f}    勝率: {best_row['win_rate']:.2f}%")
        pdf.body(f"トレード数: {int(best_row['trades'])}")

        if "recovery_factor" in best_row:
            pdf.body(f"Recovery Factor: {best_row['recovery_factor']:.3f}")

        if "sharpe_ratio" in best_row:
            pdf.body(
                f"Sharpe: {best_row['sharpe_ratio']:.3f}    "
                f"Sortino: {best_row['sortino_ratio']:.3f}"
            )

        if "cagr" in best_row:
            pdf.body(
                f"CAGR: {best_row['cagr']*100:.2f}%    "
                f"Calmar: {best_row['calmar_ratio']:.3f}"
            )

    if not stability_df.empty:
        stability_row = stability_df.iloc[0]
        pdf.body(
            f"総合安定度: {stability_row['overall_stability_score']} "
            f"({stability_row['rating']})"
        )

    if not monte_carlo_summary.empty:
        mc_row = monte_carlo_summary.iloc[0]
        pdf.body(f"Monte Carlo評価: {mc_row['rating']}")

    pdf.h2("Equity Curve")
    equity_values = equity_df["equity"].tolist() if not equity_df.empty else []
    _draw_line_chart(pdf, equity_values, color=(46, 139, 63), zero_line=True)

    pdf.h2("Drawdown Curve")
    drawdown_values = (
        [-v for v in equity_df["drawdown"].tolist()] if not equity_df.empty else []
    )
    _draw_line_chart(pdf, drawdown_values, color=(192, 57, 43), zero_line=False)

    pdf.h2("総合ランキング 上位15件")
    ranking_columns = ["rank", "net_profit", "profit_factor", "max_dd", "win_rate", "trades"]
    available_columns = [col for col in ranking_columns if col in ranking_total.columns]
    _draw_table(pdf, ranking_total, available_columns)

    return pdf


def export_pdf_report(
    output_dir: Path,
    mode: str,
    timeframe: str,
    symbol: str,
    ranking_total: pd.DataFrame,
    equity_df: pd.DataFrame,
    stability_df: pd.DataFrame,
    monte_carlo_summary: pd.DataFrame,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf = build_pdf_report(
        mode=mode,
        timeframe=timeframe,
        symbol=symbol,
        ranking_total=ranking_total,
        equity_df=equity_df,
        stability_df=stability_df,
        monte_carlo_summary=monte_carlo_summary,
    )

    output_path = output_dir / "report.pdf"
    pdf.output(str(output_path))

    return output_path

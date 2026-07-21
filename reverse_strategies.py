"""Reverses one or more already-computed strategies (ranking rows from the
現在の結果 job, or already-saved library entries) and re-tests each as a
brand-new candidate. Writes full per-target analysis (trade_log/equity_curve/
yearly/monthly/stability/monte_carlo) plus a combined ranking_total.csv into
a dedicated per-job directory (output/reversed/{job_id}/) - nothing gets
auto-saved to the library here; the dashboard's 反転ストラテジー tab reads
this directory read-only (GET /api/tools/reverse/{job_id}/results and
.../rows/{rank}/results), and only saves a specific row to the library when
the user clicks 🔖 on it (POST .../rows/{rank}/save - a plain synchronous
file-copy + registry write, no re-computation needed since everything here
is already fully computed).

"Reversing" a strategy means:
- Dual-direction mode (long_condition_tree and/or short_condition_tree set):
  swap the two trees, so what used to trigger a long entry now triggers a
  short one and vice versa.
- Single-direction mode (plain condition_tree + a `direction` flag): flip
  `direction` long<->short, keeping the same entry trigger.

Invoked by api_server.py's POST /api/tools/reverse, via the same subprocess
pattern every other tool script uses (see api_server.py's module docstring
for why main.py's own optimizer can't run in-process on Windows - this
script doesn't use ProcessPoolExecutor itself, but stays on the same
subprocess pattern rather than introducing a second, different code path).
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from engine.data_loader import find_data_file, load_price_data
from engine.backtest_engine import compute_is_intraday, run_backtest
from engine.params import reconstruct_params_from_row
from engine.strategy_registry import get_strategy
from main import (
    build_monthly_analysis,
    calculate_advanced_metrics,
    calculate_stability_metrics,
    export_single_strategy_analysis,
    resolve_output_dir,
)


def reverse_params(params: dict) -> dict:
    reversed_params = dict(params)
    if params.get("long_condition_tree") is not None or params.get("short_condition_tree") is not None:
        reversed_params["long_condition_tree"] = params.get("short_condition_tree")
        reversed_params["short_condition_tree"] = params.get("long_condition_tree")
    else:
        reversed_params["direction"] = "short" if params.get("direction") == "long" else "long"
    return reversed_params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="選択したストラテジーをエントリー方向反転で再検証する")
    parser.add_argument("--job-id", required=True, help="出力先 output/reversed/{job-id}/ に使うジョブID")
    parser.add_argument(
        "--targets",
        required=True,
        help="反転対象のJSON配列。各要素は "
        '{"type":"rank","symbol":...,"timeframe":...,"rank":N,"name":...} '
        '(結果のランキング一覧由来) または '
        '{"type":"strategy","strategy_id":"..."} (ライブラリ由来)',
    )
    return parser.parse_args()


def load_target_params(target: dict) -> tuple[dict, str, str, str]:
    """Returns (params, symbol, timeframe, display_name) for one target."""
    if target["type"] == "strategy":
        entry = get_strategy(target["strategy_id"])
        return entry["params"], entry["symbol"], entry["timeframe"], entry["name"]

    symbol = target["symbol"]
    timeframe = target["timeframe"]
    ranking_path = resolve_output_dir(symbol, timeframe) / "ranking_total.csv"
    if not ranking_path.exists():
        raise FileNotFoundError(f"{ranking_path} が見つかりません。先に通常のバックテストを実行してください。")

    ranking_total = pd.read_csv(ranking_path)
    matches = ranking_total[ranking_total["rank"] == target["rank"]]
    if matches.empty:
        raise ValueError(f"rank={target['rank']} がranking_total.csvに見つかりません。")

    row = matches.iloc[0].to_dict()
    params = reconstruct_params_from_row(row)
    name = target.get("name") or f"rank{target['rank']}"
    return params, symbol, timeframe, name


def main() -> None:
    args = parse_args()
    targets = json.loads(args.targets)

    batch_dir = Path("output") / "reversed" / args.job_id
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    rows = []

    for i, target in enumerate(targets, start=1):
        params, symbol, timeframe, name = load_target_params(target)
        reversed_p = reverse_params(params)

        cache_key = (symbol, timeframe)
        if cache_key not in price_cache:
            price_cache[cache_key] = load_price_data(find_data_file(timeframe, symbol))
        df = price_cache[cache_key]
        is_intraday = compute_is_intraday(df["datetime"])

        # スカラー指標(PF/純利益/...)はrun_backtestの戻り値にparamsが
        # そのままecho-backされる(engine/backtest_engine.py参照)ので、これが
        # そのままranking_total.csvの1行になる。ファイル出力側は
        # export_single_strategy_analysisにそのまま任せる(yearly/monthly/
        # stability/monte_carloの各CSV形式を正確に再現するのが目的で、
        # ここで手書きし直すとズレるリスクがあるため、run_backtestの二重実行
        # を許容してでも既存の実装をそのまま再利用する)。
        result, _ = run_backtest(df=df, params=reversed_p, return_trades=True, is_intraday=is_intraday)

        row_dir = batch_dir / str(i)
        row_dir.mkdir(parents=True, exist_ok=True)
        analysis = export_single_strategy_analysis(df, reversed_p, row_dir, mc_simulations=None)
        stability = calculate_stability_metrics(analysis["trade_log"], analysis["yearly_df"], analysis["monthly_df"])
        advanced = calculate_advanced_metrics(analysis["trade_log"], analysis["monthly_df"])

        result.update(
            {
                "rank": i,
                "name": f"{name}-反転",
                "symbol": symbol,
                "timeframe": timeframe,
                "yearly_stability_score": stability["yearly_stability_score"],
                "monthly_stability_score": stability["monthly_stability_score"],
                "overall_stability_score": stability["overall_stability_score"],
                "stability_rating": stability["rating"],
                "sharpe_ratio": advanced["sharpe_ratio"],
                "sortino_ratio": advanced["sortino_ratio"],
                "cagr": advanced["cagr"],
                "calmar_ratio": advanced["calmar_ratio"],
            }
        )
        rows.append(result)

        print(f"[{i}/{len(targets)}] {name} を反転しました (rank={i})")

    ranking_total = pd.DataFrame(rows)
    ranking_path = batch_dir / "ranking_total.csv"
    ranking_total.to_csv(ranking_path, index=False, encoding="utf-8-sig")

    print(f"反転完了: {len(targets)}件")
    print(f"出力: {ranking_path}")


if __name__ == "__main__":
    main()

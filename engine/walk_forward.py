from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Callable, Iterable

import pandas as pd


@dataclass(frozen=True)
class WalkForwardWindow:
    window_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WalkForwardPeriodResult:
    window_id: int

    train_start: str
    train_end: str
    test_start: str
    test_end: str

    best_param_id: str

    in_sample_profit: float
    in_sample_pf: float
    in_sample_win_rate: float
    in_sample_max_dd: float
    in_sample_trades: int

    out_sample_profit: float
    out_sample_pf: float
    out_sample_win_rate: float
    out_sample_max_dd: float
    out_sample_trades: int

    passed: bool


@dataclass
class WalkForwardSummary:
    total_windows: int
    passed_windows: int
    pass_rate: float

    oos_total_profit: float
    oos_avg_profit: float
    oos_avg_pf: float
    oos_avg_win_rate: float
    oos_worst_dd: float
    oos_total_trades: int

    wf_score: float


class WalkForwardTester:
    """
    Walk Forward Test engine.

    目的:
    - 過去期間でパラメータ最適化
    - 未来期間でそのパラメータを検証
    - OOS性能をまとめてスコア化

    使い方の前提:
    optimizer_func:
        train_df を受け取り、ランキング済み結果 DataFrame を返す関数

    backtest_func:
        test_df と parameter dict を受け取り、結果 dict を返す関数
    """

    def __init__(
        self,
        train_years: int = 10,
        test_years: int = 1,
        step_years: int = 1,
        min_train_rows: int = 1000,
        min_test_rows: int = 100,
        min_oos_pf: float = 1.0,
        min_oos_trades: int = 5,
    ) -> None:
        if train_years <= 0:
            raise ValueError("train_years must be greater than 0")
        if test_years <= 0:
            raise ValueError("test_years must be greater than 0")
        if step_years <= 0:
            raise ValueError("step_years must be greater than 0")

        self.train_years = train_years
        self.test_years = test_years
        self.step_years = step_years
        self.min_train_rows = min_train_rows
        self.min_test_rows = min_test_rows
        self.min_oos_pf = min_oos_pf
        self.min_oos_trades = min_oos_trades

    def build_windows(
        self,
        df: pd.DataFrame,
        datetime_col: str = "datetime",
    ) -> list[WalkForwardWindow]:
        if datetime_col not in df.columns:
            raise ValueError(f"datetime column not found: {datetime_col}")

        work = df.copy()
        work[datetime_col] = pd.to_datetime(work[datetime_col])
        work = work.sort_values(datetime_col)

        start = work[datetime_col].min().normalize()
        end = work[datetime_col].max().normalize()

        windows: list[WalkForwardWindow] = []
        window_id = 1

        train_start = start

        while True:
            train_end = train_start + pd.DateOffset(years=self.train_years)
            test_start = train_end
            test_end = test_start + pd.DateOffset(years=self.test_years)

            if test_end > end:
                break

            windows.append(
                WalkForwardWindow(
                    window_id=window_id,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )

            window_id += 1
            train_start = train_start + pd.DateOffset(years=self.step_years)

        return windows

    def run(
        self,
        df: pd.DataFrame,
        optimizer_func: Callable[[pd.DataFrame], pd.DataFrame],
        backtest_func: Callable[[pd.DataFrame, dict[str, Any]], dict[str, Any]],
        datetime_col: str = "datetime",
        output_detail_csv: str | None = None,
        output_summary_csv: str | None = None,
    ) -> tuple[WalkForwardSummary, pd.DataFrame]:
        if datetime_col not in df.columns:
            raise ValueError(f"datetime column not found: {datetime_col}")

        work = df.copy()
        work[datetime_col] = pd.to_datetime(work[datetime_col])
        work = work.sort_values(datetime_col).reset_index(drop=True)

        windows = self.build_windows(work, datetime_col=datetime_col)

        period_results: list[WalkForwardPeriodResult] = []

        for window in windows:
            train_df = work[
                (work[datetime_col] >= window.train_start)
                & (work[datetime_col] < window.train_end)
            ].copy()

            test_df = work[
                (work[datetime_col] >= window.test_start)
                & (work[datetime_col] < window.test_end)
            ].copy()

            if len(train_df) < self.min_train_rows:
                continue

            if len(test_df) < self.min_test_rows:
                continue

            ranking_df = optimizer_func(train_df)

            if ranking_df is None or len(ranking_df) == 0:
                continue

            best_row = ranking_df.iloc[0]
            best_params = self._extract_params_from_row(best_row)

            test_result = backtest_func(test_df, best_params)

            in_sample_profit = self._get_float(best_row, ["net_profit", "profit", "total_profit"])
            in_sample_pf = self._get_float(best_row, ["profit_factor", "pf"])
            in_sample_win_rate = self._get_float(best_row, ["win_rate", "winrate"])
            in_sample_max_dd = self._get_float(best_row, ["max_dd", "max_drawdown"])
            in_sample_trades = self._get_int(best_row, ["trades", "total_trades", "trade_count"])

            out_sample_profit = self._get_float(test_result, ["net_profit", "profit", "total_profit"])
            out_sample_pf = self._get_float(test_result, ["profit_factor", "pf"])
            out_sample_win_rate = self._get_float(test_result, ["win_rate", "winrate"])
            out_sample_max_dd = self._get_float(test_result, ["max_dd", "max_drawdown"])
            out_sample_trades = self._get_int(test_result, ["trades", "total_trades", "trade_count"])

            passed = (
                out_sample_pf >= self.min_oos_pf
                and out_sample_trades >= self.min_oos_trades
                and out_sample_profit > 0
            )

            best_param_id = str(best_row.get("param_id", best_row.get("id", "")))

            period_results.append(
                WalkForwardPeriodResult(
                    window_id=window.window_id,
                    train_start=str(window.train_start.date()),
                    train_end=str(window.train_end.date()),
                    test_start=str(window.test_start.date()),
                    test_end=str(window.test_end.date()),
                    best_param_id=best_param_id,
                    in_sample_profit=in_sample_profit,
                    in_sample_pf=in_sample_pf,
                    in_sample_win_rate=in_sample_win_rate,
                    in_sample_max_dd=in_sample_max_dd,
                    in_sample_trades=in_sample_trades,
                    out_sample_profit=out_sample_profit,
                    out_sample_pf=out_sample_pf,
                    out_sample_win_rate=out_sample_win_rate,
                    out_sample_max_dd=out_sample_max_dd,
                    out_sample_trades=out_sample_trades,
                    passed=passed,
                )
            )

        detail_df = pd.DataFrame([asdict(r) for r in period_results])
        summary = self._build_summary(detail_df)

        if output_detail_csv:
            detail_df.to_csv(output_detail_csv, index=False, encoding="utf-8-sig")

        if output_summary_csv:
            pd.DataFrame([asdict(summary)]).to_csv(
                output_summary_csv,
                index=False,
                encoding="utf-8-sig",
            )

        return summary, detail_df

    def _build_summary(self, detail_df: pd.DataFrame) -> WalkForwardSummary:
        if detail_df.empty:
            return WalkForwardSummary(
                total_windows=0,
                passed_windows=0,
                pass_rate=0.0,
                oos_total_profit=0.0,
                oos_avg_profit=0.0,
                oos_avg_pf=0.0,
                oos_avg_win_rate=0.0,
                oos_worst_dd=0.0,
                oos_total_trades=0,
                wf_score=0.0,
            )

        total_windows = int(len(detail_df))
        passed_windows = int(detail_df["passed"].sum())
        pass_rate = passed_windows / total_windows if total_windows > 0 else 0.0

        oos_total_profit = float(detail_df["out_sample_profit"].sum())
        oos_avg_profit = float(detail_df["out_sample_profit"].mean())
        oos_avg_pf = float(detail_df["out_sample_pf"].replace([float("inf")], pd.NA).dropna().mean())
        oos_avg_win_rate = float(detail_df["out_sample_win_rate"].mean())
        oos_worst_dd = float(detail_df["out_sample_max_dd"].max())
        oos_total_trades = int(detail_df["out_sample_trades"].sum())

        wf_score = self._calc_wf_score(
            pass_rate=pass_rate,
            oos_total_profit=oos_total_profit,
            oos_avg_pf=oos_avg_pf,
            oos_avg_win_rate=oos_avg_win_rate,
            oos_worst_dd=oos_worst_dd,
            oos_total_trades=oos_total_trades,
        )

        return WalkForwardSummary(
            total_windows=total_windows,
            passed_windows=passed_windows,
            pass_rate=pass_rate,
            oos_total_profit=oos_total_profit,
            oos_avg_profit=oos_avg_profit,
            oos_avg_pf=oos_avg_pf,
            oos_avg_win_rate=oos_avg_win_rate,
            oos_worst_dd=oos_worst_dd,
            oos_total_trades=oos_total_trades,
            wf_score=wf_score,
        )

    def _calc_wf_score(
        self,
        pass_rate: float,
        oos_total_profit: float,
        oos_avg_pf: float,
        oos_avg_win_rate: float,
        oos_worst_dd: float,
        oos_total_trades: int,
    ) -> float:
        if oos_total_trades <= 0:
            return 0.0

        pf_score = max(0.0, min(oos_avg_pf / 2.0, 2.0))
        win_score = max(0.0, min(oos_avg_win_rate / 60.0, 2.0))
        profit_score = max(0.0, oos_total_profit)

        if oos_worst_dd <= 0:
            dd_score = 1.0
        else:
            dd_score = max(0.0, min(oos_total_profit / oos_worst_dd, 5.0))

        trade_score = min(oos_total_trades / 100.0, 2.0)

        score = (
            pass_rate * 35.0
            + pf_score * 20.0
            + win_score * 10.0
            + dd_score * 20.0
            + trade_score * 5.0
            + min(profit_score, 100.0) * 0.1
        )

        return round(float(score), 6)

    def _extract_params_from_row(self, row: pd.Series) -> dict[str, Any]:
        ignore_cols = {
            "param_id",
            "id",
            "score",
            "rank_score",
            "net_profit",
            "profit",
            "total_profit",
            "profit_factor",
            "pf",
            "win_rate",
            "winrate",
            "max_dd",
            "max_drawdown",
            "trades",
            "total_trades",
            "trade_count",
            "year_stability",
            "month_stability",
            "max_win_streak",
            "max_loss_streak",
            "walk_forward_score",
            "wf_score",
        }

        params: dict[str, Any] = {}

        for key, value in row.items():
            if key in ignore_cols:
                continue

            if pd.isna(value):
                continue

            if isinstance(value, (int, float, str, bool)):
                params[str(key)] = value

        return params

    def _get_float(self, source: Any, keys: Iterable[str], default: float = 0.0) -> float:
        for key in keys:
            try:
                if isinstance(source, dict):
                    value = source.get(key, None)
                else:
                    value = source.get(key, None)

                if value is None or pd.isna(value):
                    continue

                return float(value)
            except Exception:
                continue

        return default

    def _get_int(self, source: Any, keys: Iterable[str], default: int = 0) -> int:
        for key in keys:
            try:
                if isinstance(source, dict):
                    value = source.get(key, None)
                else:
                    value = source.get(key, None)

                if value is None or pd.isna(value):
                    continue

                return int(value)
            except Exception:
                continue

        return default


def run_walk_forward_test(
    df: pd.DataFrame,
    optimizer_func: Callable[[pd.DataFrame], pd.DataFrame],
    backtest_func: Callable[[pd.DataFrame, dict[str, Any]], dict[str, Any]],
    datetime_col: str = "datetime",
    train_years: int = 10,
    test_years: int = 1,
    step_years: int = 1,
    output_detail_csv: str | None = None,
    output_summary_csv: str | None = None,
) -> tuple[WalkForwardSummary, pd.DataFrame]:
    tester = WalkForwardTester(
        train_years=train_years,
        test_years=test_years,
        step_years=step_years,
    )

    return tester.run(
        df=df,
        optimizer_func=optimizer_func,
        backtest_func=backtest_func,
        datetime_col=datetime_col,
        output_detail_csv=output_detail_csv,
        output_summary_csv=output_summary_csv,
    )
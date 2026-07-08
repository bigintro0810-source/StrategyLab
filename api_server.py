"""FastAPI backend for Strategy Lab's web frontend (frontend/).

Thin wrapper over the existing, already-tested CLI pipeline (main.py) - reuses
the exact subprocess invocation pattern gui_app.py already established (see
that file's module docstring for why: main.py's optimizer loop uses
ProcessPoolExecutor, which on Windows uses the "spawn" start method, so a
backtest must run in a separate process - never imported and called
in-process here). No backtest logic is reimplemented in this file; it only
spawns main.py, parses its output CSVs into JSON, and serves already-existing
engine/main.py data (price data, saved strategies, indicator registry) over
HTTP.

Run with: uvicorn api_server:app --reload
"""

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.conditions import INDICATOR_REGISTRY
from engine.strategy_registry import get_strategy, list_strategies
from main import find_data_file, load_price_data, pip_size_for_symbol, resolve_output_dir

app = FastAPI(title="Strategy Lab API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store - single-user local app, no Redis/Celery needed.
JOBS: dict[str, dict[str, Any]] = {}


class BacktestRequest(BaseModel):
    mode: str = "dev"
    timeframe: str = "15m"
    symbol: str = "USDJPY"
    optimizer: str = "grid"
    direction: str = "short"
    condition_tree: Optional[dict] = None
    # Node-level condition-tree optimization: N complete condition_tree
    # variants (each a full tree, differing only in one node's swept value),
    # pre-built client-side since the frontend already holds the live tree
    # in memory and can substitute a value at a specific node far more
    # simply than the backend re-deriving "which node" from a path/ID
    # scheme. When set, this REPLACES condition_tree as the swept dimension
    # - main.py's grid optimizer already cross-multiplies over whatever's
    # in the params dict via itertools.product regardless of value type, so
    # a list of N dicts here needs no new grid-building logic at all.
    condition_tree_variants: Optional[list[dict]] = None
    # When both are set, the engine evaluates them simultaneously (one shared
    # position slot, no hedging) instead of the single condition_tree+direction
    # above - see engine/backtest_engine.py::_run_dual_direction_backtest.
    long_condition_tree: Optional[dict] = None
    short_condition_tree: Optional[dict] = None
    save_as: Optional[str] = None
    # Optional parameter sweep: {"ema_length": [180, 190, 200, ...]} - any key
    # here overrides the single-value default below with a value list, so
    # main.py's grid optimizer (itertools.product across param_space) produces
    # one ranking_total.csv row per combination instead of just one row.
    param_ranges: Optional[dict[str, list[float]]] = None
    rr: float = 1.2
    use_weekend_exit: bool = True
    weekend_exit_hour: int = 4
    use_daily_exit: bool = False
    daily_exit_hour: int = 4
    spread_pips: float = 0.0
    slippage_pips: float = 0.0
    commission_per_trade: float = 0.0
    use_atr_trailing_stop: bool = False
    atr_trailing_length: int = 14
    atr_trailing_multiplier: float = 2.0
    use_max_dd_stop: bool = False
    max_dd_stop_pips: float = 100.0
    use_consecutive_loss_stop: bool = False
    consecutive_loss_stop_count: int = 3
    consecutive_loss_stop_bars: int = 100
    # "market" (default) is today's unchanged behavior; "limit"/"stop" are
    # not yet supported together with long_condition_tree/short_condition_tree
    # (dual-direction) - main.py/run_backtest raises a clear error if both
    # are set rather than silently ignoring one.
    entry_method: str = "market"
    entry_offset_pips: float = 10.0
    # Position sizing - default off, in which case profit/net_profit/etc stay
    # in raw pip units exactly as before (implied 1 lot). See
    # engine/backtest_engine.py's _pip_value_in_account_currency/_compute_lot_size.
    use_position_sizing: bool = False
    position_sizing_method: str = "risk_percent"
    initial_capital: float = 1_000_000.0
    account_currency: str = "JPY"
    risk_percent: float = 1.0
    fixed_lot_size: float = 0.1
    contract_size: float = 100_000.0
    conversion_rate: float = 150.0
    # Breakeven stop move and partial profit-taking - both default off (SL/TP
    # stay exactly as RR-computed at entry unless opted in).
    use_breakeven_stop: bool = False
    breakeven_trigger_rr: float = 0.5
    use_partial_tp: bool = False
    partial_tp_rr: float = 1.0
    partial_tp_fraction: float = 0.5
    # Multi-stage partial profit-taking: a list of {"rr": ..., "fraction":
    # ...} levels, each closing `fraction` of whatever REMAINS of the
    # position once price reaches that level's RR distance. When set, this
    # replaces partial_tp_rr/partial_tp_fraction above (which stay as the
    # fallback for older saved strategies with no partial_tp_levels key -
    # see engine/backtest_engine.py::_resolve_partial_tp_levels).
    partial_tp_levels: Optional[list[dict]] = None


def _build_strategy_config(req: "BacktestRequest") -> Path:
    """Mirrors gui_app.py's condition-builder tab: wrap the condition tree
    plus the base BacktestConfig-shaped params into a strategy_configs/*.json
    file, consumed by main.py via the existing --strategy-config mechanism."""
    params = {
        "ema_length": [200],
        "min_body_pips": [20.0],
        "max_body_pips": [0.0],
        "max_wick_pips": [0.0],
        "lookahead_bars": [15],
        "breakout_bars": [30],
        "ema_distance_pips": [50.0],
        "rsi_min": [70.0],
        "rr": [req.rr],
        "session_start": [8],
        "session_end": [3],
        "use_weekend_exit": [req.use_weekend_exit],
        "weekend_exit_hour": [req.weekend_exit_hour],
        "use_daily_exit": [req.use_daily_exit],
        "daily_exit_hour": [req.daily_exit_hour],
        "spread_pips": [req.spread_pips],
        "slippage_pips": [req.slippage_pips],
        "commission_per_trade": [req.commission_per_trade],
        "use_atr_trailing_stop": [req.use_atr_trailing_stop],
        "atr_trailing_length": [req.atr_trailing_length],
        "atr_trailing_multiplier": [req.atr_trailing_multiplier],
        "use_max_dd_stop": [req.use_max_dd_stop],
        "max_dd_stop_pips": [req.max_dd_stop_pips],
        "use_consecutive_loss_stop": [req.use_consecutive_loss_stop],
        "consecutive_loss_stop_count": [req.consecutive_loss_stop_count],
        "consecutive_loss_stop_bars": [req.consecutive_loss_stop_bars],
        "entry_method": [req.entry_method],
        "entry_offset_pips": [req.entry_offset_pips],
        "use_position_sizing": [req.use_position_sizing],
        "position_sizing_method": [req.position_sizing_method],
        "initial_capital": [req.initial_capital],
        "account_currency": [req.account_currency],
        "risk_percent": [req.risk_percent],
        "fixed_lot_size": [req.fixed_lot_size],
        "contract_size": [req.contract_size],
        "conversion_rate": [req.conversion_rate],
        "use_breakeven_stop": [req.use_breakeven_stop],
        "breakeven_trigger_rr": [req.breakeven_trigger_rr],
        "use_partial_tp": [req.use_partial_tp],
        "partial_tp_rr": [req.partial_tp_rr],
        "partial_tp_fraction": [req.partial_tp_fraction],
        "partial_tp_levels": [req.partial_tp_levels],
        # Without this, run_backtest()/engine/filters.py silently fall back to
        # pip_size=0.01 (main.py's own default grid always sets this
        # per-symbol, but --strategy-config JSON files don't unless told to) -
        # correct for JPY pairs, but 100x too large for EURUSD/GBPUSD/AUDUSD,
        # silently corrupting every _pips-suffixed filter threshold and the
        # spread/slippage cost above for 3 of the 7 supported symbols.
        "pip_size": [pip_size_for_symbol(req.symbol)],
        # Needed for multi-timeframe conditions (a condition node whose
        # timeframe differs from req.timeframe) so the engine knows which
        # symbol's other-timeframe data file to load.
        "symbol": [req.symbol],
        "direction": [req.direction],
        "condition_tree": req.condition_tree_variants if req.condition_tree_variants else [req.condition_tree],
        "long_condition_tree": [req.long_condition_tree],
        "short_condition_tree": [req.short_condition_tree],
    }
    for key, values in (req.param_ranges or {}).items():
        if key in params:
            params[key] = values

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"api_{timestamp}_{uuid.uuid4().hex[:6]}"
    config_path = Path("strategy_configs") / f"{name}.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"name": name, "params": params}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return config_path


def _extract_friendly_error(stderr: str) -> str:
    """Distills a raw Python traceback down to a short, Japanese, non-scary
    summary for display in the UI - the raw traceback (file paths, line
    numbers, "Traceback (most recent call last):", etc.) is useful for
    debugging but not something a non-technical user should have to read
    first. Many of this codebase's own raised exceptions already carry a
    Japanese message (engine/conditions.py's ValueErrors, main.py's
    find_data_file's FileNotFoundError, etc.), so extracting just the
    final "ExceptionType: message" line of the traceback alone surfaces
    something readable in most real cases. The full stderr stays available
    separately (the job's `error` field) for anyone who wants to see - or
    report - the raw traceback."""
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    if not lines:
        return "原因不明のエラーが発生しました。しばらく待ってからもう一度お試しください。"

    last_line = lines[-1]
    match = re.match(r"^([\w.]+(?:Error|Exception)):\s*(.*)$", last_line)
    if match:
        exc_type, message = match.group(1), match.group(2)
        if message:
            return f"バックテストの実行中にエラーが発生しました。\n\n{message}"
        return (
            f"バックテストの実行中にエラーが発生しました({exc_type})。\n\n"
            "下の「詳細を見る」を開いて、内容を販売元にお問い合わせください。"
        )

    return (
        f"バックテストの実行中にエラーが発生しました。\n\n{last_line}\n\n"
        "下の「詳細を見る」を開いて、内容を販売元にお問い合わせください。"
    )


async def _run_job(job_id: str, cmd: list[str]) -> None:
    JOBS[job_id]["status"] = "running"

    # Without an explicit UTF-8 override, main.py's own stdout/stderr encoding
    # follows the Windows console codepage (e.g. cp932 on a Japanese-locale
    # machine), so its Japanese messages arrive here as mojibake once decoded
    # as UTF-8 below. PYTHON_COLORS=0 disables Python 3.13's colorized
    # tracebacks (raw ANSI escape codes), which otherwise pollute stderr and
    # break _extract_friendly_error's "ExceptionType: message" regex match.
    child_env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PYTHON_COLORS": "0",
    }

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_env,
    )
    stdout, stderr = await process.communicate()

    JOBS[job_id]["stdout"] = stdout.decode("utf-8", errors="replace")
    JOBS[job_id]["stderr"] = stderr.decode("utf-8", errors="replace")
    JOBS[job_id]["status"] = "done" if process.returncode == 0 else "error"


@app.post("/api/backtests")
async def create_backtest(req: BacktestRequest) -> dict:
    job_id = uuid.uuid4().hex

    cmd = [
        sys.executable, "main.py",
        "--mode", req.mode,
        "--timeframe", req.timeframe,
        "--symbol", req.symbol,
        "--optimizer", req.optimizer,
    ]

    if req.condition_tree is not None or req.long_condition_tree is not None or req.short_condition_tree is not None:
        config_path = _build_strategy_config(req)
        cmd += ["--strategy-config", str(config_path)]

    if req.save_as:
        cmd += ["--save-as", req.save_as]

    JOBS[job_id] = {
        "status": "queued",
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "stdout": "",
        "stderr": "",
    }

    asyncio.create_task(_run_job(job_id, cmd))

    return {"job_id": job_id}


@app.post("/api/backtests/{job_id}/rows/{rank}")
async def rerun_ranking_row(job_id: str, rank: int) -> dict:
    """Re-runs one specific ranking_total.csv row from an already-completed
    job - lets the dashboard's ranking table show any row's own equity
    curve/trade history/stats, not just the auto-run top-ranked one. Returns
    a NEW job_id, pollable through the exact same /api/backtests/{job_id}
    and /api/backtests/{job_id}/results endpoints as any other backtest -
    no new frontend polling logic needed beyond what already exists."""
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"job status is {job['status']}, not done")

    new_job_id = uuid.uuid4().hex
    cmd = [
        sys.executable, "rerun_ranking_row.py",
        "--symbol", job["symbol"],
        "--timeframe", job["timeframe"],
        "--rank", str(rank),
    ]

    JOBS[new_job_id] = {
        "status": "queued",
        "symbol": job["symbol"],
        "timeframe": job["timeframe"],
        "stdout": "",
        "stderr": "",
    }

    asyncio.create_task(_run_job(new_job_id, cmd))

    return {"job_id": new_job_id}


@app.get("/api/backtests/{job_id}")
async def get_backtest_status(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    error = job["stderr"][-2000:] if job["status"] == "error" else None
    return {
        "status": job["status"],
        "stdout_tail": job["stdout"][-2000:],
        "error": error,
        "error_summary": _extract_friendly_error(error) if error else None,
    }


def _read_csv_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/api/backtests/{job_id}/results")
async def get_backtest_results(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"job status is {job['status']}, not done")

    output_dir = resolve_output_dir(job["symbol"], job["timeframe"])

    return {
        "ranking_total": _read_csv_records(output_dir / "ranking_total.csv"),
        "equity_curve": _read_csv_records(output_dir / "equity_curve.csv"),
        "trade_log": _read_csv_records(output_dir / "trade_log.csv"),
        "monte_carlo_summary": _read_csv_records(output_dir / "monte_carlo_summary.csv"),
        "yearly_analysis": _read_csv_records(output_dir / "yearly_analysis.csv"),
        "monthly_analysis": _read_csv_records(output_dir / "monthly_analysis.csv"),
        "stability_analysis": _read_csv_records(output_dir / "stability_analysis.csv"),
    }


@app.get("/api/price-data")
async def get_price_data(
    symbol: str = "USDJPY",
    timeframe: str = "15m",
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 1000,
) -> list[dict]:
    df = load_price_data(find_data_file(timeframe, symbol))

    if start:
        df = df[df["datetime"] >= start]
    if end:
        df = df[df["datetime"] <= end]

    df = df.tail(limit)

    return json.loads(df.to_json(orient="records", date_format="iso"))


# Indicator display metadata for the condition-builder UI - mirrors
# gui_app.py's BUILDER_INDICATORS dict, served as data instead of duplicated
# in every client.
INDICATOR_LABELS: dict[str, str] = {
    "close": "終値",
    "open": "始値",
    "high": "高値",
    "low": "安値",
    "candle_body": "実体(終値-始値、符号あり)",
    "ema": "EMA",
    "sma": "SMA",
    "rsi": "RSI",
    "atr": "ATR",
    "highest_high": "直近高値(N本)",
    "lowest_low": "直近安値(N本)",
    "donchian_mid": "ドンチアン中央値",
    "bollinger_upper": "ボリンジャー上限",
    "bollinger_middle": "ボリンジャー中央",
    "bollinger_lower": "ボリンジャー下限",
    "macd_line": "MACDライン",
    "macd_signal": "MACDシグナル",
    "stochastic_k": "ストキャスティクス%K",
    "stochastic_d": "ストキャスティクス%D",
    "adx": "ADX",
    "plus_di": "+DI",
    "minus_di": "-DI",
    "supertrend_line": "SuperTrendライン",
    "supertrend_direction": "SuperTrend方向(1=上昇/-1=下降)",
    "fvg_bullish": "FVG(強気)",
    "fvg_bearish": "FVG(弱気)",
    "order_block_bullish": "オーダーブロック(強気)",
    "order_block_bearish": "オーダーブロック(弱気)",
    "liquidity_sweep_bullish": "流動性スイープ(強気)",
    "liquidity_sweep_bearish": "流動性スイープ(弱気)",
    "bos_bullish": "BOS(強気/上昇継続)",
    "bos_bearish": "BOS(弱気/下降継続)",
    "choch_bullish": "CHoCH(強気/上昇転換)",
    "choch_bearish": "CHoCH(弱気/下降転換)",
    "breaker_block_bullish": "ブレイカーブロック(強気)",
    "breaker_block_bearish": "ブレイカーブロック(弱気)",
    "vwap": "VWAP(出来高加重平均価格・日次リセット)",
    "hour": "時刻(JST)",
    "weekday": "曜日(0=月〜6=日)",
    "month": "月(1〜12)",
    "killzone_asian": "Kill Zone: アジア(東京時間08-10時)",
    "killzone_london": "Kill Zone: ロンドン(ロンドン時間07-10時)",
    "killzone_newyork": "Kill Zone: ニューヨーク(NY時間07-10時)",
    "killzone_london_close": "Kill Zone: ロンドンクローズ(ロンドン時間15-17時)",
    "prev_day_high": "前日高値",
    "prev_day_low": "前日安値",
    "pivot": "ピボット(PP)",
    "pivot_r1": "ピボットR1",
    "pivot_s1": "ピボットS1",
    "adr": "ADR(平均日次レンジ)",
    "ichimoku_tenkan": "一目均衡表: 転換線",
    "ichimoku_kijun": "一目均衡表: 基準線",
    "ichimoku_senkou_a": "一目均衡表: 先行スパンA",
    "ichimoku_senkou_b": "一目均衡表: 先行スパンB",
    "fib_level": "フィボナッチ水準",
    "bullish_candle": "陽線",
    "bearish_candle": "陰線",
    "large_bullish_candle": "大陽線",
    "large_bearish_candle": "大陰線",
    "small_bullish_candle": "小陽線",
    "small_bearish_candle": "小陰線",
    "doji": "十字線(Doji)",
    "long_upper_wick": "長い上ヒゲ",
    "long_lower_wick": "長い下ヒゲ",
    "no_upper_wick": "上ヒゲなし",
    "no_lower_wick": "下ヒゲなし",
    "marubozu_bullish": "陽の丸坊主",
    "marubozu_bearish": "陰の丸坊主",
    "pin_bar_bullish": "ピンバー(強気)",
    "pin_bar_bearish": "ピンバー(弱気)",
    "hammer": "ハンマー",
    "hanging_man": "吊り線",
    "inverted_hammer": "逆ハンマー",
    "shooting_star": "シューティングスター",
    "engulfing_bullish": "包み足(強気)",
    "engulfing_bearish": "包み足(弱気)",
    "inside_bar": "Inside Bar",
    "outside_bar": "Outside Bar",
    "tweezer_top": "Tweezer Top",
    "tweezer_bottom": "Tweezer Bottom",
    "harami_bullish": "はらみ足(強気)",
    "harami_bearish": "はらみ足(弱気)",
    "gap_up": "ギャップアップ",
    "gap_down": "ギャップダウン",
    "morning_star": "Morning Star",
    "evening_star": "Evening Star",
    "three_white_soldiers": "Three White Soldiers",
    "three_black_crows": "Three Black Crows",
    "rising_three_methods": "Rising Three Methods",
    "falling_three_methods": "Falling Three Methods",
    "consecutive_bullish_candles": "N本連続陽線",
    "consecutive_bearish_candles": "N本連続陰線",
    "consecutive_higher_highs": "高値更新連続",
    "consecutive_lower_lows": "安値更新連続",
    "body_larger_than_average": "実体が平均よりX倍大きい",
    "wick_ratio_at_least": "ヒゲ率X%以上",
    "body_ratio_at_least": "実体率X%以上",
    # 距離系 (2026-07-08追加): dist_{close,high,low}_{target} - 33種
    "dist_close_ema": "終値とEMAの距離",
    "dist_high_ema": "高値とEMAの距離",
    "dist_low_ema": "安値とEMAの距離",
    "dist_close_sma": "終値とSMAの距離",
    "dist_high_sma": "高値とSMAの距離",
    "dist_low_sma": "安値とSMAの距離",
    "dist_close_vwap": "終値とVWAPの距離",
    "dist_high_vwap": "高値とVWAPの距離",
    "dist_low_vwap": "安値とVWAPの距離",
    "dist_close_supertrend": "終値とSuperTrendの距離",
    "dist_high_supertrend": "高値とSuperTrendの距離",
    "dist_low_supertrend": "安値とSuperTrendの距離",
    "dist_close_pivot": "終値とピボットの距離",
    "dist_high_pivot": "高値とピボットの距離",
    "dist_low_pivot": "安値とピボットの距離",
    "dist_close_prev_day_high": "終値と前日高値の距離",
    "dist_high_prev_day_high": "高値と前日高値の距離",
    "dist_low_prev_day_high": "安値と前日高値の距離",
    "dist_close_prev_day_low": "終値と前日安値の距離",
    "dist_high_prev_day_low": "高値と前日安値の距離",
    "dist_low_prev_day_low": "安値と前日安値の距離",
    "dist_close_donchian_upper": "終値とドンチアン上限の距離",
    "dist_high_donchian_upper": "高値とドンチアン上限の距離",
    "dist_low_donchian_upper": "安値とドンチアン上限の距離",
    "dist_close_donchian_lower": "終値とドンチアン下限の距離",
    "dist_high_donchian_lower": "高値とドンチアン下限の距離",
    "dist_low_donchian_lower": "安値とドンチアン下限の距離",
    "dist_close_bb_upper": "終値とボリンジャー上限の距離",
    "dist_high_bb_upper": "高値とボリンジャー上限の距離",
    "dist_low_bb_upper": "安値とボリンジャー上限の距離",
    "dist_close_bb_lower": "終値とボリンジャー下限の距離",
    "dist_high_bb_lower": "高値とボリンジャー下限の距離",
    "dist_low_bb_lower": "安値とボリンジャー下限の距離",
    "dist_order_block_bullish": "直近の強気オーダーブロックまでの距離",
    "dist_order_block_bearish": "直近の弱気オーダーブロックまでの距離",
    "dist_fvg_bullish": "直近の強気FVGまでの距離",
    "dist_fvg_bearish": "直近の弱気FVGまでの距離",
    "dist_bos_bullish": "直近の上昇スイング高値(BOS節目)までの距離",
    "dist_bos_bearish": "直近の下降スイング安値(BOS節目)までの距離",
    "minutes_since_london_open": "ロンドンオープンからの経過分数",
    "minutes_since_ny_open": "NYオープンからの経過分数",
    # 傾き系
    "ema_rising": "EMA上昇中",
    "ema_falling": "EMA下降中",
    "vwap_rising": "VWAP上昇中",
    "vwap_falling": "VWAP下降中",
    "supertrend_rising": "SuperTrendライン上昇中",
    "supertrend_falling": "SuperTrendライン下降中",
    "rsi_rising": "RSI上昇中",
    "rsi_falling": "RSI下降中",
    "adx_rising": "ADX上昇中",
    "adx_falling": "ADX下降中",
    "macd_rising": "MACD上昇中",
    "macd_falling": "MACD下降中",
    "atr_rising": "ATR増加中",
    "atr_falling": "ATR減少中",
    "ema_slope_degrees": "EMA傾き(角度)",
    "ema_roc": "EMA変化率(%)",
    "atr_roc": "ATR変化率(%)",
    "higher_high": "Higher High(切り上がる高値)",
    "higher_low": "Higher Low(切り上がる安値)",
    "lower_high": "Lower High(切り下がる高値)",
    "lower_low": "Lower Low(切り下がる安値)",
    # 価格位置
    "bb_percent_b": "ボリンジャー%B(0=下限,0.5=中央,1=上限)",
    "donchian_percent_position": "ドンチアン内位置(0=下限,1=上限)",
    "dist_to_ema_atr_ratio": "EMAからの距離(ATR倍数)",
    "today_range_pct_of_adr": "本日レンジのADR比率(%)",
    "prev_day_mid": "前日レンジ中央値",
    "today_range_position": "本日レンジ内位置(0=安値,1=高値)",
    "dist_to_fib": "フィボナッチ水準までの距離",
    # 統計系
    "rolling_mean_high": "過去N本平均高値",
    "rolling_mean_low": "過去N本平均安値",
    "avg_body_size": "平均実体サイズ",
    "max_body_size": "最大実体サイズ",
    "min_body_size": "最小実体サイズ",
    "body_size_std": "実体サイズの標準偏差",
    "avg_upper_wick": "平均上ヒゲサイズ",
    "avg_lower_wick": "平均下ヒゲサイズ",
    "atr_rolling_mean": "ATRの移動平均",
    "atr_deviation": "ATRの移動平均からの乖離",
    "close_rolling_std": "終値の標準偏差(ヒストリカルボラティリティ)",
    "rsi_rolling_mean": "RSIの移動平均",
    "rsi_deviation": "RSIの移動平均からの乖離",
    "adx_rolling_mean": "ADXの移動平均",
    "macd_rolling_mean": "MACDの移動平均",
    "percentile_rank_rsi": "RSIの過去N本内パーセンタイル順位",
    "percentile_rank_atr": "ATRの過去N本内パーセンタイル順位",
    "percentile_rank_body": "実体サイズの過去N本内パーセンタイル順位",
    "zscore_close": "終値のZスコア",
    "zscore_rsi": "RSIのZスコア",
    "zscore_atr": "ATRのZスコア",
    "is_max_body_of_n": "過去N本で実体最大",
    "is_min_atr_of_n": "過去N本でATR最小",
    "is_max_rsi_of_n": "過去N本でRSI最高",
    # エントリー専用イベント
    "bb_width": "ボリンジャーバンド幅",
    "bb_squeeze": "ボリンジャースクイーズ発生中",
    "bb_expansion": "ボリンジャーエクスパンション開始",
    "supertrend_flip_bullish": "SuperTrend買い転換",
    "supertrend_flip_bearish": "SuperTrend売り転換",
    "today_new_high": "当日高値更新",
    "today_new_low": "当日安値更新",
    # 一瞬だけ起きる変化
    "rsi_divergence_bearish": "RSI弱気ダイバージェンス(簡易版)",
    "rsi_divergence_bullish": "RSI強気ダイバージェンス(簡易版)",
    "macd_divergence_bearish": "MACD弱気ダイバージェンス(簡易版)",
    "macd_divergence_bullish": "MACD強気ダイバージェンス(簡易版)",
    "ema_perfect_order_bullish": "EMAパーフェクトオーダー成立(強気)",
    "ema_perfect_order_bearish": "EMAパーフェクトオーダー成立(弱気)",
    "ema_perfect_order_broken_bullish": "EMAパーフェクトオーダー崩れ(強気→崩壊)",
    "ema_perfect_order_broken_bearish": "EMAパーフェクトオーダー崩れ(弱気→崩壊)",
    "first_pullback_after_breakout_bullish": "上抜けブレイクアウト後の初押し",
    "first_pullback_after_breakout_bearish": "下抜けブレイクアウト後の初戻り",
    "fvg_first_retest_bullish": "強気FVGの初回リテスト",
    "fvg_first_retest_bearish": "弱気FVGの初回リテスト",
    "order_block_first_retest_bullish": "強気オーダーブロックの初回リテスト",
    "order_block_first_retest_bearish": "弱気オーダーブロックの初回リテスト",
    # 2026-07-08追加(2巡目): 追加ローソク足パターン
    "long_legged_doji": "足長同時線(両ヒゲとも長い十字線)",
    "dragonfly_doji": "トンボ(下ヒゲのみ長い十字線)",
    "gravestone_doji": "塔婆(上ヒゲのみ長い十字線)",
    "spinning_top": "スピニングトップ(小実体+両ヒゲ均衡)",
    "kicker_bullish": "蹴り足(強気、ギャップ+大陽線)",
    "kicker_bearish": "蹴り足(弱気、ギャップ+大陰線)",
    "belt_hold_bullish": "Belt Hold(強気)",
    "belt_hold_bearish": "Belt Hold(弱気)",
    "abandoned_baby_bullish": "捨て子線(強気)",
    "abandoned_baby_bearish": "捨て子線(弱気)",
    "three_inside_up": "Three Inside Up",
    "three_inside_down": "Three Inside Down",
    "three_outside_up": "Three Outside Up",
    "three_outside_down": "Three Outside Down",
    "dist_to_round_number": "キリ番(ラウンドナンバー)までの距離",
    # チャートパターン (engine/chart_patterns.py)
    "double_top_breakdown": "ダブルトップ ネックライン割れ",
    "double_bottom_breakout": "ダブルボトム ネックライン突破",
    "triple_top_breakdown": "トリプルトップ ネックライン割れ",
    "triple_bottom_breakout": "トリプルボトム ネックライン突破",
    "head_and_shoulders_breakdown": "ヘッド&ショルダーズ ネックライン割れ",
    "inverse_head_and_shoulders_breakout": "逆ヘッド&ショルダーズ ネックライン突破",
    "ascending_triangle_breakout": "上昇三角形 上抜けブレイク",
    "descending_triangle_breakdown": "下降三角形 下抜けブレイク",
    "symmetrical_triangle_breakout_bullish": "対称三角形 上抜けブレイク",
    "symmetrical_triangle_breakout_bearish": "対称三角形 下抜けブレイク",
    "rising_wedge_breakdown": "上昇ウェッジ 下抜けブレイク",
    "falling_wedge_breakout": "下降ウェッジ 上抜けブレイク",
    "bull_flag_breakout": "ブルフラッグ ブレイクアウト",
    "bear_flag_breakdown": "ベアフラッグ ブレイクダウン",
    "bullish_pennant_breakout": "強気ペナント ブレイクアウト",
    "bearish_pennant_breakdown": "弱気ペナント ブレイクダウン",
    "in_range_box": "レンジボックス継続中",
    "range_box_breakout_bullish": "レンジボックス 上抜けブレイク",
    "range_box_breakdown_bearish": "レンジボックス 下抜けブレイク",
    # 2026-07-08追加(3巡目)
    "cci": "CCI(商品チャネル指数)",
    "williams_r": "Williams %R",
    "parabolic_sar_line": "パラボリックSAR",
    "parabolic_sar_direction": "パラボリックSAR方向(1=上昇/-1=下降)",
    "aroon_up": "Aroon Up",
    "aroon_down": "Aroon Down",
    "aroon_oscillator": "Aroonオシレーター",
    "choppiness_index": "チョピネス指数(高い=レンジ,低い=トレンド)",
    "keltner_upper": "ケルトナーチャネル上限",
    "keltner_middle": "ケルトナーチャネル中央(EMA)",
    "keltner_lower": "ケルトナーチャネル下限",
    "obv": "OBV(オンバランスボリューム)",
    "ad_line": "A/Dライン(蓄積/分配)",
    "mfi": "MFI(マネーフローインデックス)",
    "cmf": "CMF(チャイキンマネーフロー)",
    "woodie_pivot": "Woodieピボット",
    "woodie_r1": "Woodie R1",
    "woodie_s1": "Woodie S1",
    "woodie_r2": "Woodie R2",
    "woodie_s2": "Woodie S2",
    "camarilla_r1": "Camarilla R1",
    "camarilla_r2": "Camarilla R2",
    "camarilla_r3": "Camarilla R3",
    "camarilla_r4": "Camarilla R4",
    "camarilla_s1": "Camarilla S1",
    "camarilla_s2": "Camarilla S2",
    "camarilla_s3": "Camarilla S3",
    "camarilla_s4": "Camarilla S4",
    "fib_pivot": "フィボナッチピボット",
    "fib_pivot_r1": "フィボナッチピボット R1",
    "fib_pivot_r2": "フィボナッチピボット R2",
    "fib_pivot_r3": "フィボナッチピボット R3",
    "fib_pivot_s1": "フィボナッチピボット S1",
    "fib_pivot_s2": "フィボナッチピボット S2",
    "fib_pivot_s3": "フィボナッチピボット S3",
    "ttm_squeeze": "TTMスクイーズ(BBがケルトナー内側)",
    "ttm_squeeze_release": "TTMスクイーズ解放",
    "ichimoku_price_vs_cloud": "一目: 価格vs雲(1=上,-1=下,0=中)",
    "ichimoku_kumo_twist_bullish": "一目: 雲のねじれ(強気転換)",
    "ichimoku_kumo_twist_bearish": "一目: 雲のねじれ(弱気転換)",
    "ichimoku_chikou_signal": "一目: 遅行スパン相当シグナル(1=上,-1=下)",
    "linreg_slope_atr_ratio": "線形回帰の傾き(ATR倍率)",
    "linreg_angle_degrees": "線形回帰の傾き(角度)",
    "linreg_value": "線形回帰ライン値",
    "linreg_upper": "線形回帰チャネル上限",
    "linreg_lower": "線形回帰チャネル下限",
    "ha_bullish": "平均足 陽線",
    "ha_bearish": "平均足 陰線",
    "ha_strong_bullish": "平均足 強い陽線(下ヒゲなし)",
    "ha_strong_bearish": "平均足 強い陰線(上ヒゲなし)",
    "gartley_bullish": "ガートレーパターン(強気)",
    "gartley_bearish": "ガートレーパターン(弱気)",
    "bat_bullish": "バットパターン(強気)",
    "bat_bearish": "バットパターン(弱気)",
    "butterfly_bullish": "バタフライパターン(強気)",
    "butterfly_bearish": "バタフライパターン(弱気)",
    "crab_bullish": "クラブパターン(強気)",
    "crab_bearish": "クラブパターン(弱気)",
    # 2026-07-08追加(4巡目)
    "ab_cd_bullish": "AB=CDパターン(強気)",
    "ab_cd_bearish": "AB=CDパターン(弱気)",
    "three_drives_bullish": "スリードライブ(強気、3連続安値切り下げ後の反転)",
    "three_drives_bearish": "スリードライブ(弱気、3連続高値切り上げ後の反転)",
    "uptrend_line_break": "上昇トレンドライン割れ",
    "downtrend_line_break": "下降トレンドライン抜け",
    "ascending_channel_break": "上昇平行チャネル下抜け",
    "descending_channel_break": "下降平行チャネル上抜け",
    "false_breakout_bullish_reversal": "フェイクブレイク(下放れ失敗からの反転)",
    "false_breakout_bearish_reversal": "フェイクブレイク(上放れ失敗からの反転)",
    "nr4": "NR4(過去4本で最も狭いレンジ)",
    "nr7": "NR7(過去7本で最も狭いレンジ)",
    "volume_climax_bullish": "出来高クライマックス(強気)",
    "volume_climax_bearish": "出来高クライマックス(弱気)",
    # 2026-07-08追加(5巡目、HFM記事の未実装分)
    "saucer_top": "ソーサートップ(丸い天井)",
    "saucer_bottom": "ソーサーボトム(丸い底)",
    "ascending_rectangle_breakout": "上昇レクタングル ブレイクアウト",
    "descending_rectangle_breakdown": "下降レクタングル ブレイクダウン",
    "broadening_formation_breakout_bullish": "ブロードニングフォーメーション 上抜けブレイク",
    "broadening_formation_breakout_bearish": "ブロードニングフォーメーション 下抜けブレイク",
    "diamond_formation_breakout_bullish": "ダイヤモンドフォーメーション 上抜けブレイク",
    "diamond_formation_breakout_bearish": "ダイヤモンドフォーメーション 下抜けブレイク",
    "cup_with_handle_breakout": "カップウィズハンドル ブレイクアウト",
}

# Per-indicator adjustable parameters, in the exact order/names/defaults
# INDICATOR_REGISTRY's lambdas accept - drives the condition-builder UI's
# per-indicator param inputs. Previously the UI only ever exposed a single
# hardcoded "length" field (INDICATORS_NEEDING_PERIOD, a flat boolean set) -
# indicators with more than one real parameter (bollinger's num_std, macd's
# fast/slow/signal, stochastic's 3 periods, ichimoku's 3 periods, fib's
# ratio) silently kept their Python-side default for every param except
# length. This schema lets the frontend render one input per declared
# param instead. type="choice" (fib's ratio) renders a <select> of the
# listed values rather than a free-entry number field, since only specific
# conventional ratios are meaningful.
INDICATOR_PARAM_SPECS: dict[str, list[dict]] = {
    "ema": [{"name": "length", "label": "期間", "default": 200, "type": "int"}],
    "sma": [{"name": "length", "label": "期間", "default": 200, "type": "int"}],
    "rsi": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
    "atr": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
    "highest_high": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "lowest_low": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "donchian_mid": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "bollinger_upper": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "float"},
    ],
    "bollinger_middle": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "float"},
    ],
    "bollinger_lower": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "float"},
    ],
    "macd_line": [
        {"name": "fast", "label": "短期", "default": 12, "type": "int"},
        {"name": "slow", "label": "長期", "default": 26, "type": "int"},
        {"name": "signal", "label": "シグナル期間", "default": 9, "type": "int"},
    ],
    "macd_signal": [
        {"name": "fast", "label": "短期", "default": 12, "type": "int"},
        {"name": "slow", "label": "長期", "default": 26, "type": "int"},
        {"name": "signal", "label": "シグナル期間", "default": 9, "type": "int"},
    ],
    "stochastic_k": [
        {"name": "k_period", "label": "%K期間", "default": 14, "type": "int"},
        {"name": "d_period", "label": "%D期間", "default": 3, "type": "int"},
        {"name": "smooth", "label": "平滑化", "default": 3, "type": "int"},
    ],
    "stochastic_d": [
        {"name": "k_period", "label": "%K期間", "default": 14, "type": "int"},
        {"name": "d_period", "label": "%D期間", "default": 3, "type": "int"},
        {"name": "smooth", "label": "平滑化", "default": 3, "type": "int"},
    ],
    "adx": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
    "plus_di": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
    "minus_di": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
    "supertrend_line": [
        {"name": "length", "label": "期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 3.0, "type": "float"},
    ],
    "supertrend_direction": [
        {"name": "length", "label": "期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 3.0, "type": "float"},
    ],
    "liquidity_sweep_bullish": [{"name": "length", "label": "期間", "default": 5, "type": "int"}],
    "liquidity_sweep_bearish": [{"name": "length", "label": "期間", "default": 5, "type": "int"}],
    "bos_bullish": [{"name": "length", "label": "期間", "default": 5, "type": "int"}],
    "bos_bearish": [{"name": "length", "label": "期間", "default": 5, "type": "int"}],
    "choch_bullish": [{"name": "length", "label": "期間", "default": 5, "type": "int"}],
    "choch_bearish": [{"name": "length", "label": "期間", "default": 5, "type": "int"}],
    "adr": [{"name": "adr_period", "label": "期間", "default": 14, "type": "int"}],
    "ichimoku_tenkan": [
        {"name": "tenkan_period", "label": "転換線期間", "default": 9, "type": "int"},
        {"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"},
        {"name": "senkou_b_period", "label": "先行スパンB期間", "default": 52, "type": "int"},
    ],
    "ichimoku_kijun": [
        {"name": "tenkan_period", "label": "転換線期間", "default": 9, "type": "int"},
        {"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"},
        {"name": "senkou_b_period", "label": "先行スパンB期間", "default": 52, "type": "int"},
    ],
    "ichimoku_senkou_a": [
        {"name": "tenkan_period", "label": "転換線期間", "default": 9, "type": "int"},
        {"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"},
        {"name": "senkou_b_period", "label": "先行スパンB期間", "default": 52, "type": "int"},
    ],
    "ichimoku_senkou_b": [
        {"name": "tenkan_period", "label": "転換線期間", "default": 9, "type": "int"},
        {"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"},
        {"name": "senkou_b_period", "label": "先行スパンB期間", "default": 52, "type": "int"},
    ],
    "fib_level": [
        {"name": "length", "label": "期間", "default": 20, "type": "int"},
        {
            "name": "ratio", "label": "比率", "default": 0.618, "type": "choice",
            "choices": [0.236, 0.382, 0.5, 0.618, 0.786, 1.272, 1.618],
        },
    ],
    "large_bullish_candle": [
        {"name": "lookback", "label": "平均算出期間", "default": 20, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 1.5, "type": "choice", "choices": [1.2, 1.5, 2.0, 2.5, 3.0]},
    ],
    "large_bearish_candle": [
        {"name": "lookback", "label": "平均算出期間", "default": 20, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 1.5, "type": "choice", "choices": [1.2, 1.5, 2.0, 2.5, 3.0]},
    ],
    "small_bullish_candle": [
        {"name": "lookback", "label": "平均算出期間", "default": 20, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 0.5, "type": "choice", "choices": [0.3, 0.4, 0.5, 0.6, 0.7]},
    ],
    "small_bearish_candle": [
        {"name": "lookback", "label": "平均算出期間", "default": 20, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 0.5, "type": "choice", "choices": [0.3, 0.4, 0.5, 0.6, 0.7]},
    ],
    "doji": [
        {"name": "body_ratio_threshold", "label": "実体率しきい値", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15, 0.2]},
    ],
    "long_upper_wick": [
        {"name": "wick_ratio_threshold", "label": "上ヒゲ率しきい値", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7, 0.8]},
    ],
    "long_lower_wick": [
        {"name": "wick_ratio_threshold", "label": "下ヒゲ率しきい値", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7, 0.8]},
    ],
    "no_upper_wick": [
        {"name": "threshold", "label": "上ヒゲ率上限", "default": 0.05, "type": "choice", "choices": [0.02, 0.05, 0.1]},
    ],
    "no_lower_wick": [
        {"name": "threshold", "label": "下ヒゲ率上限", "default": 0.05, "type": "choice", "choices": [0.02, 0.05, 0.1]},
    ],
    "marubozu_bullish": [
        {"name": "body_ratio_threshold", "label": "実体率しきい値", "default": 0.95, "type": "choice", "choices": [0.9, 0.95, 0.98]},
    ],
    "marubozu_bearish": [
        {"name": "body_ratio_threshold", "label": "実体率しきい値", "default": 0.95, "type": "choice", "choices": [0.9, 0.95, 0.98]},
    ],
    "pin_bar_bullish": [
        {"name": "body_ratio_max", "label": "実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
        {"name": "wick_ratio_min", "label": "ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
    ],
    "pin_bar_bearish": [
        {"name": "body_ratio_max", "label": "実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
        {"name": "wick_ratio_min", "label": "ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
    ],
    "hammer": [
        {"name": "body_ratio_max", "label": "実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
        {"name": "lower_wick_ratio_min", "label": "下ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
        {"name": "upper_wick_ratio_max", "label": "上ヒゲ率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "hanging_man": [
        {"name": "body_ratio_max", "label": "実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
        {"name": "lower_wick_ratio_min", "label": "下ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
        {"name": "upper_wick_ratio_max", "label": "上ヒゲ率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "inverted_hammer": [
        {"name": "body_ratio_max", "label": "実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
        {"name": "upper_wick_ratio_min", "label": "上ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
        {"name": "lower_wick_ratio_max", "label": "下ヒゲ率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "shooting_star": [
        {"name": "body_ratio_max", "label": "実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
        {"name": "upper_wick_ratio_min", "label": "上ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
        {"name": "lower_wick_ratio_max", "label": "下ヒゲ率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "tweezer_top": [
        {"name": "tolerance_pct", "label": "高値一致許容度", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15, 0.2]},
    ],
    "tweezer_bottom": [
        {"name": "tolerance_pct", "label": "安値一致許容度", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15, 0.2]},
    ],
    "morning_star": [
        {"name": "small_body_ratio", "label": "中央実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
    ],
    "evening_star": [
        {"name": "small_body_ratio", "label": "中央実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
    ],
    "consecutive_bullish_candles": [
        {"name": "n", "label": "連続本数", "default": 3, "type": "int"},
    ],
    "consecutive_bearish_candles": [
        {"name": "n", "label": "連続本数", "default": 3, "type": "int"},
    ],
    "consecutive_higher_highs": [
        {"name": "n", "label": "連続本数", "default": 3, "type": "int"},
    ],
    "consecutive_lower_lows": [
        {"name": "n", "label": "連続本数", "default": 3, "type": "int"},
    ],
    "body_larger_than_average": [
        {"name": "lookback", "label": "平均算出期間", "default": 20, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 1.5, "type": "choice", "choices": [1.2, 1.5, 2.0, 2.5, 3.0]},
    ],
    "wick_ratio_at_least": [
        {"name": "threshold_pct", "label": "ヒゲ率(%)", "default": 50.0, "type": "choice", "choices": [30.0, 40.0, 50.0, 60.0, 70.0]},
    ],
    "body_ratio_at_least": [
        {"name": "threshold_pct", "label": "実体率(%)", "default": 50.0, "type": "choice", "choices": [30.0, 40.0, 50.0, 60.0, 70.0]},
    ],
}

# 2026-07-08追加分。dist_{close,high,low}_{target}の33種は同じ target ごとに
# 全く同じパラメータ仕様を共有するので、ここだけループで生成する
# (indicator_pool.py::_DISTANCE_TARGET_PARAMSと同じ考え方)。
_DIST_TARGET_PARAM_SPECS: dict[str, list[dict]] = {
    "ema": [{"name": "length", "label": "期間", "default": 200, "type": "int"}],
    "sma": [{"name": "length", "label": "期間", "default": 200, "type": "int"}],
    "vwap": [],
    "supertrend": [
        {"name": "length", "label": "期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5, 4.0]},
    ],
    "pivot": [],
    "prev_day_high": [],
    "prev_day_low": [],
    "donchian_upper": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "donchian_lower": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "bb_upper": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "bb_lower": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
}
for _target, _spec in _DIST_TARGET_PARAM_SPECS.items():
    for _price_source in ("close", "high", "low"):
        INDICATOR_PARAM_SPECS[f"dist_{_price_source}_{_target}"] = list(_spec)

# 傾き系: rising/falling は基となる系列自身のパラメータ + 共通の lookback。
_SLOPE_PARAM_SPECS: dict[str, list[dict]] = {
    "ema": [{"name": "length", "label": "期間", "default": 200, "type": "int"}],
    "vwap": [],
    "supertrend": [
        {"name": "length", "label": "期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5, 4.0]},
    ],
    "rsi": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
    "adx": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
    "macd": [
        {"name": "fast", "label": "短期", "default": 12, "type": "int"},
        {"name": "slow", "label": "長期", "default": 26, "type": "int"},
        {"name": "signal", "label": "シグナル期間", "default": 9, "type": "int"},
    ],
    "atr": [{"name": "length", "label": "期間", "default": 14, "type": "int"}],
}
for _series, _spec in _SLOPE_PARAM_SPECS.items():
    for _direction in ("rising", "falling"):
        INDICATOR_PARAM_SPECS[f"{_series}_{_direction}"] = [
            *_spec, {"name": "lookback", "label": "比較対象(Nバー前)", "default": 1, "type": "int"},
        ]

INDICATOR_PARAM_SPECS.update({
    "dist_order_block_bullish": [],
    "dist_order_block_bearish": [],
    "dist_fvg_bullish": [],
    "dist_fvg_bearish": [],
    "dist_bos_bullish": [{"name": "length", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "dist_bos_bearish": [{"name": "length", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "minutes_since_london_open": [],
    "minutes_since_ny_open": [],
    "ema_slope_degrees": [
        {"name": "length", "label": "EMA期間", "default": 200, "type": "int"},
        {"name": "lookback", "label": "比較対象(Nバー前)", "default": 5, "type": "int"},
    ],
    "ema_roc": [
        {"name": "length", "label": "EMA期間", "default": 200, "type": "int"},
        {"name": "lookback", "label": "比較対象(Nバー前)", "default": 5, "type": "int"},
    ],
    "atr_roc": [
        {"name": "length", "label": "ATR期間", "default": 14, "type": "int"},
        {"name": "lookback", "label": "比較対象(Nバー前)", "default": 1, "type": "int"},
    ],
    "higher_high": [{"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "higher_low": [{"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "lower_high": [{"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "lower_low": [{"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "bb_percent_b": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "donchian_percent_position": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "dist_to_ema_atr_ratio": [
        {"name": "ema_length", "label": "EMA期間", "default": 200, "type": "int"},
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
    ],
    "today_range_pct_of_adr": [{"name": "adr_period", "label": "ADR算出期間", "default": 14, "type": "int"}],
    "prev_day_mid": [],
    "today_range_position": [],
    "dist_to_fib": [
        {"name": "length", "label": "期間", "default": 20, "type": "int"},
        {
            "name": "ratio", "label": "比率", "default": 0.618, "type": "choice",
            "choices": [0.236, 0.382, 0.5, 0.618, 0.786, 1.272, 1.618],
        },
    ],
    "rolling_mean_high": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "rolling_mean_low": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "avg_body_size": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "max_body_size": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "min_body_size": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "body_size_std": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "avg_upper_wick": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "avg_lower_wick": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "atr_rolling_mean": [
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
        {"name": "window", "label": "移動平均期間", "default": 20, "type": "int"},
    ],
    "atr_deviation": [
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
        {"name": "window", "label": "移動平均期間", "default": 20, "type": "int"},
    ],
    "close_rolling_std": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "rsi_rolling_mean": [
        {"name": "rsi_length", "label": "RSI期間", "default": 14, "type": "int"},
        {"name": "window", "label": "移動平均期間", "default": 20, "type": "int"},
    ],
    "rsi_deviation": [
        {"name": "rsi_length", "label": "RSI期間", "default": 14, "type": "int"},
        {"name": "window", "label": "移動平均期間", "default": 20, "type": "int"},
    ],
    "adx_rolling_mean": [
        {"name": "adx_length", "label": "ADX期間", "default": 14, "type": "int"},
        {"name": "window", "label": "移動平均期間", "default": 20, "type": "int"},
    ],
    "macd_rolling_mean": [{"name": "window", "label": "移動平均期間", "default": 20, "type": "int"}],
    "percentile_rank_rsi": [
        {"name": "rsi_length", "label": "RSI期間", "default": 14, "type": "int"},
        {"name": "window", "label": "算出対象期間", "default": 100, "type": "int"},
    ],
    "percentile_rank_atr": [
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
        {"name": "window", "label": "算出対象期間", "default": 200, "type": "int"},
    ],
    "percentile_rank_body": [{"name": "window", "label": "算出対象期間", "default": 50, "type": "int"}],
    "zscore_close": [{"name": "window", "label": "算出対象期間", "default": 20, "type": "int"}],
    "zscore_rsi": [
        {"name": "rsi_length", "label": "RSI期間", "default": 14, "type": "int"},
        {"name": "window", "label": "算出対象期間", "default": 20, "type": "int"},
    ],
    "zscore_atr": [
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
        {"name": "window", "label": "算出対象期間", "default": 20, "type": "int"},
    ],
    "is_max_body_of_n": [{"name": "window", "label": "算出対象期間", "default": 100, "type": "int"}],
    "is_min_atr_of_n": [
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
        {"name": "window", "label": "算出対象期間", "default": 50, "type": "int"},
    ],
    "is_max_rsi_of_n": [
        {"name": "rsi_length", "label": "RSI期間", "default": 14, "type": "int"},
        {"name": "window", "label": "算出対象期間", "default": 200, "type": "int"},
    ],
    "bb_width": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "bb_squeeze": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
        {"name": "window", "label": "比較対象期間", "default": 100, "type": "int"},
        {"name": "percentile", "label": "下位何%以下をスクイーズとするか", "default": 10.0, "type": "choice", "choices": [5.0, 10.0, 15.0, 20.0]},
    ],
    "bb_expansion": [
        {"name": "period", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
        {"name": "window", "label": "比較対象期間", "default": 100, "type": "int"},
        {"name": "percentile", "label": "下位何%以下をスクイーズとするか", "default": 10.0, "type": "choice", "choices": [5.0, 10.0, 15.0, 20.0]},
    ],
    "supertrend_flip_bullish": [
        {"name": "length", "label": "期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5, 4.0]},
    ],
    "supertrend_flip_bearish": [
        {"name": "length", "label": "期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "倍率", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5, 4.0]},
    ],
    "today_new_high": [],
    "today_new_low": [],
    "rsi_divergence_bearish": [
        {"name": "length", "label": "価格の高値更新判定期間", "default": 20, "type": "int"},
        {"name": "rsi_length", "label": "RSI期間", "default": 14, "type": "int"},
    ],
    "rsi_divergence_bullish": [
        {"name": "length", "label": "価格の安値更新判定期間", "default": 20, "type": "int"},
        {"name": "rsi_length", "label": "RSI期間", "default": 14, "type": "int"},
    ],
    "macd_divergence_bearish": [{"name": "length", "label": "価格の高値更新判定期間", "default": 20, "type": "int"}],
    "macd_divergence_bullish": [{"name": "length", "label": "価格の安値更新判定期間", "default": 20, "type": "int"}],
    "ema_perfect_order_bullish": [
        {"name": "length_1", "label": "EMA1(最短)", "default": 20, "type": "int"},
        {"name": "length_2", "label": "EMA2", "default": 50, "type": "int"},
        {"name": "length_3", "label": "EMA3", "default": 100, "type": "int"},
        {"name": "length_4", "label": "EMA4(最長)", "default": 200, "type": "int"},
    ],
    "ema_perfect_order_bearish": [
        {"name": "length_1", "label": "EMA1(最短)", "default": 20, "type": "int"},
        {"name": "length_2", "label": "EMA2", "default": 50, "type": "int"},
        {"name": "length_3", "label": "EMA3", "default": 100, "type": "int"},
        {"name": "length_4", "label": "EMA4(最長)", "default": 200, "type": "int"},
    ],
    "ema_perfect_order_broken_bullish": [
        {"name": "length_1", "label": "EMA1(最短)", "default": 20, "type": "int"},
        {"name": "length_2", "label": "EMA2", "default": 50, "type": "int"},
        {"name": "length_3", "label": "EMA3", "default": 100, "type": "int"},
        {"name": "length_4", "label": "EMA4(最長)", "default": 200, "type": "int"},
    ],
    "ema_perfect_order_broken_bearish": [
        {"name": "length_1", "label": "EMA1(最短)", "default": 20, "type": "int"},
        {"name": "length_2", "label": "EMA2", "default": 50, "type": "int"},
        {"name": "length_3", "label": "EMA3", "default": 100, "type": "int"},
        {"name": "length_4", "label": "EMA4(最長)", "default": 200, "type": "int"},
    ],
    "first_pullback_after_breakout_bullish": [{"name": "length", "label": "ブレイクアウト判定期間", "default": 20, "type": "int"}],
    "first_pullback_after_breakout_bearish": [{"name": "length", "label": "ブレイクアウト判定期間", "default": 20, "type": "int"}],
    "fvg_first_retest_bullish": [],
    "fvg_first_retest_bearish": [],
    "order_block_first_retest_bullish": [],
    "order_block_first_retest_bearish": [],
})

# 2026-07-08追加(2巡目): 追加ローソク足パターン + ラウンドナンバー距離 +
# チャートパターン(engine/chart_patterns.py)
INDICATOR_PARAM_SPECS.update({
    "long_legged_doji": [
        {"name": "body_ratio_threshold", "label": "実体率しきい値", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15, 0.2]},
        {"name": "wick_ratio_min", "label": "両ヒゲ率下限", "default": 0.35, "type": "choice", "choices": [0.25, 0.35, 0.45]},
    ],
    "dragonfly_doji": [
        {"name": "body_ratio_threshold", "label": "実体率しきい値", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
        {"name": "lower_wick_ratio_min", "label": "下ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
        {"name": "upper_wick_ratio_max", "label": "上ヒゲ率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "gravestone_doji": [
        {"name": "body_ratio_threshold", "label": "実体率しきい値", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
        {"name": "upper_wick_ratio_min", "label": "上ヒゲ率下限", "default": 0.6, "type": "choice", "choices": [0.5, 0.6, 0.7]},
        {"name": "lower_wick_ratio_max", "label": "下ヒゲ率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "spinning_top": [
        {"name": "body_ratio_max", "label": "実体率上限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
        {"name": "wick_ratio_min", "label": "両ヒゲ率下限", "default": 0.3, "type": "choice", "choices": [0.2, 0.3, 0.4]},
    ],
    "kicker_bullish": [
        {"name": "body_ratio_threshold", "label": "実体率下限", "default": 0.7, "type": "choice", "choices": [0.5, 0.6, 0.7, 0.8]},
    ],
    "kicker_bearish": [
        {"name": "body_ratio_threshold", "label": "実体率下限", "default": 0.7, "type": "choice", "choices": [0.5, 0.6, 0.7, 0.8]},
    ],
    "belt_hold_bullish": [
        {"name": "lower_wick_ratio_max", "label": "下ヒゲ率上限", "default": 0.05, "type": "choice", "choices": [0.02, 0.05, 0.1]},
        {"name": "body_ratio_min", "label": "実体率下限", "default": 0.7, "type": "choice", "choices": [0.6, 0.7, 0.8]},
    ],
    "belt_hold_bearish": [
        {"name": "upper_wick_ratio_max", "label": "上ヒゲ率上限", "default": 0.05, "type": "choice", "choices": [0.02, 0.05, 0.1]},
        {"name": "body_ratio_min", "label": "実体率下限", "default": 0.7, "type": "choice", "choices": [0.6, 0.7, 0.8]},
    ],
    "abandoned_baby_bullish": [
        {"name": "small_body_ratio", "label": "中央実体率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "abandoned_baby_bearish": [
        {"name": "small_body_ratio", "label": "中央実体率上限", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "three_inside_up": [],
    "three_inside_down": [],
    "three_outside_up": [],
    "three_outside_down": [],
    "dist_to_round_number": [
        {"name": "pip_size", "label": "1pipのサイズ(JPYペア/XAUUSD=0.01, XAGUSD=0.001, それ以外=0.0001)", "default": 0.01, "type": "choice", "choices": [0.01, 0.001, 0.0001]},
    ],
    "double_top_breakdown": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance_atr_mult", "label": "水準一致許容度(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.3, 0.5, 0.75, 1.0]},
    ],
    "double_bottom_breakout": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance_atr_mult", "label": "水準一致許容度(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.3, 0.5, 0.75, 1.0]},
    ],
    "triple_top_breakdown": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance_atr_mult", "label": "水準一致許容度(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.3, 0.5, 0.75, 1.0]},
    ],
    "triple_bottom_breakout": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance_atr_mult", "label": "水準一致許容度(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.3, 0.5, 0.75, 1.0]},
    ],
    "head_and_shoulders_breakdown": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "shoulder_tolerance_atr_mult", "label": "両肩水準一致許容度(ATR倍率)", "default": 0.75, "type": "choice", "choices": [0.5, 0.75, 1.0]},
        {"name": "head_margin_atr_mult", "label": "頭の突出量(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.25, 0.5, 0.75]},
    ],
    "inverse_head_and_shoulders_breakout": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "shoulder_tolerance_atr_mult", "label": "両肩水準一致許容度(ATR倍率)", "default": 0.75, "type": "choice", "choices": [0.5, 0.75, 1.0]},
        {"name": "head_margin_atr_mult", "label": "頭の突出量(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.25, 0.5, 0.75]},
    ],
    "ascending_triangle_breakout": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "flat_tolerance_atr_mult", "label": "水平抵抗の一致許容度(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.3, 0.5, 0.75]},
    ],
    "descending_triangle_breakdown": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "flat_tolerance_atr_mult", "label": "水平支持の一致許容度(ATR倍率)", "default": 0.5, "type": "choice", "choices": [0.3, 0.5, 0.75]},
    ],
    "symmetrical_triangle_breakout_bullish": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
    ],
    "symmetrical_triangle_breakout_bearish": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
    ],
    "rising_wedge_breakdown": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
    ],
    "falling_wedge_breakout": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
    ],
    "bull_flag_breakout": [
        {"name": "impulse_lookback", "label": "急騰判定期間", "default": 10, "type": "int"},
        {"name": "impulse_atr_mult", "label": "急騰の強さ(ATR倍率)", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5]},
        {"name": "consolidation_window", "label": "もみ合い判定期間", "default": 10, "type": "int"},
        {"name": "consolidation_atr_mult", "label": "もみ合いの狭さ(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "bear_flag_breakdown": [
        {"name": "impulse_lookback", "label": "急落判定期間", "default": 10, "type": "int"},
        {"name": "impulse_atr_mult", "label": "急落の強さ(ATR倍率)", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5]},
        {"name": "consolidation_window", "label": "もみ合い判定期間", "default": 10, "type": "int"},
        {"name": "consolidation_atr_mult", "label": "もみ合いの狭さ(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "bullish_pennant_breakout": [
        {"name": "impulse_lookback", "label": "急騰判定期間", "default": 10, "type": "int"},
        {"name": "impulse_atr_mult", "label": "急騰の強さ(ATR倍率)", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5]},
        {"name": "consolidation_window", "label": "収束判定期間", "default": 12, "type": "int"},
        {"name": "consolidation_atr_mult", "label": "収束の狭さ(ATR倍率)", "default": 2.5, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "bearish_pennant_breakdown": [
        {"name": "impulse_lookback", "label": "急落判定期間", "default": 10, "type": "int"},
        {"name": "impulse_atr_mult", "label": "急落の強さ(ATR倍率)", "default": 3.0, "type": "choice", "choices": [2.0, 2.5, 3.0, 3.5]},
        {"name": "consolidation_window", "label": "収束判定期間", "default": 12, "type": "int"},
        {"name": "consolidation_atr_mult", "label": "収束の狭さ(ATR倍率)", "default": 2.5, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "in_range_box": [
        {"name": "window", "label": "判定期間", "default": 20, "type": "int"},
        {"name": "box_atr_mult", "label": "ボックス幅上限(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
    ],
    "range_box_breakout_bullish": [
        {"name": "window", "label": "判定期間", "default": 20, "type": "int"},
        {"name": "box_atr_mult", "label": "ボックス幅上限(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
    ],
    "range_box_breakdown_bearish": [
        {"name": "window", "label": "判定期間", "default": 20, "type": "int"},
        {"name": "box_atr_mult", "label": "ボックス幅上限(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
    ],
})

# 2026-07-08追加(3巡目)
INDICATOR_PARAM_SPECS.update({
    "cci": [{"name": "period", "label": "期間", "default": 20, "type": "int"}],
    "williams_r": [{"name": "period", "label": "期間", "default": 14, "type": "int"}],
    "parabolic_sar_line": [
        {"name": "af_start", "label": "加速係数初期値", "default": 0.02, "type": "choice", "choices": [0.01, 0.02, 0.03]},
        {"name": "af_max", "label": "加速係数上限", "default": 0.2, "type": "choice", "choices": [0.1, 0.2, 0.3]},
    ],
    "parabolic_sar_direction": [
        {"name": "af_start", "label": "加速係数初期値", "default": 0.02, "type": "choice", "choices": [0.01, 0.02, 0.03]},
        {"name": "af_max", "label": "加速係数上限", "default": 0.2, "type": "choice", "choices": [0.1, 0.2, 0.3]},
    ],
    "aroon_up": [{"name": "period", "label": "期間", "default": 14, "type": "int"}],
    "aroon_down": [{"name": "period", "label": "期間", "default": 14, "type": "int"}],
    "aroon_oscillator": [{"name": "period", "label": "期間", "default": 14, "type": "int"}],
    "choppiness_index": [{"name": "period", "label": "期間", "default": 14, "type": "int"}],
    "keltner_upper": [
        {"name": "period", "label": "EMA期間", "default": 20, "type": "int"},
        {"name": "atr_period", "label": "ATR期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "ATR倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "keltner_middle": [
        {"name": "period", "label": "EMA期間", "default": 20, "type": "int"},
        {"name": "atr_period", "label": "ATR期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "ATR倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "keltner_lower": [
        {"name": "period", "label": "EMA期間", "default": 20, "type": "int"},
        {"name": "atr_period", "label": "ATR期間", "default": 10, "type": "int"},
        {"name": "multiplier", "label": "ATR倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "obv": [],
    "ad_line": [],
    "mfi": [{"name": "period", "label": "期間", "default": 14, "type": "int"}],
    "cmf": [{"name": "period", "label": "期間", "default": 20, "type": "int"}],
    "woodie_pivot": [], "woodie_r1": [], "woodie_s1": [], "woodie_r2": [], "woodie_s2": [],
    "camarilla_r1": [], "camarilla_r2": [], "camarilla_r3": [], "camarilla_r4": [],
    "camarilla_s1": [], "camarilla_s2": [], "camarilla_s3": [], "camarilla_s4": [],
    "fib_pivot": [], "fib_pivot_r1": [], "fib_pivot_r2": [], "fib_pivot_r3": [],
    "fib_pivot_s1": [], "fib_pivot_s2": [], "fib_pivot_s3": [],
    "ttm_squeeze": [
        {"name": "bb_period", "label": "BB期間", "default": 20, "type": "int"},
        {"name": "bb_num_std", "label": "BB標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
        {"name": "kc_period", "label": "ケルトナーEMA期間", "default": 20, "type": "int"},
        {"name": "kc_atr_period", "label": "ケルトナーATR期間", "default": 10, "type": "int"},
        {"name": "kc_multiplier", "label": "ケルトナーATR倍率", "default": 1.5, "type": "choice", "choices": [1.0, 1.5, 2.0]},
    ],
    "ttm_squeeze_release": [
        {"name": "bb_period", "label": "BB期間", "default": 20, "type": "int"},
        {"name": "bb_num_std", "label": "BB標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
        {"name": "kc_period", "label": "ケルトナーEMA期間", "default": 20, "type": "int"},
        {"name": "kc_atr_period", "label": "ケルトナーATR期間", "default": 10, "type": "int"},
        {"name": "kc_multiplier", "label": "ケルトナーATR倍率", "default": 1.5, "type": "choice", "choices": [1.0, 1.5, 2.0]},
    ],
    "ichimoku_price_vs_cloud": [
        {"name": "tenkan_period", "label": "転換線期間", "default": 9, "type": "int"},
        {"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"},
        {"name": "senkou_b_period", "label": "先行スパンB期間", "default": 52, "type": "int"},
    ],
    "ichimoku_kumo_twist_bullish": [
        {"name": "tenkan_period", "label": "転換線期間", "default": 9, "type": "int"},
        {"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"},
        {"name": "senkou_b_period", "label": "先行スパンB期間", "default": 52, "type": "int"},
    ],
    "ichimoku_kumo_twist_bearish": [
        {"name": "tenkan_period", "label": "転換線期間", "default": 9, "type": "int"},
        {"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"},
        {"name": "senkou_b_period", "label": "先行スパンB期間", "default": 52, "type": "int"},
    ],
    "ichimoku_chikou_signal": [{"name": "kijun_period", "label": "基準線期間", "default": 26, "type": "int"}],
    "linreg_slope_atr_ratio": [
        {"name": "length", "label": "期間", "default": 20, "type": "int"},
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
    ],
    "linreg_angle_degrees": [
        {"name": "length", "label": "期間", "default": 20, "type": "int"},
        {"name": "atr_length", "label": "ATR期間", "default": 14, "type": "int"},
    ],
    "linreg_value": [{"name": "length", "label": "期間", "default": 20, "type": "int"}],
    "linreg_upper": [
        {"name": "length", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "linreg_lower": [
        {"name": "length", "label": "期間", "default": 20, "type": "int"},
        {"name": "num_std", "label": "標準偏差倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5]},
    ],
    "ha_bullish": [],
    "ha_bearish": [],
    "ha_strong_bullish": [
        {"name": "threshold", "label": "ヒゲ率上限", "default": 0.05, "type": "choice", "choices": [0.02, 0.05, 0.1]},
    ],
    "ha_strong_bearish": [
        {"name": "threshold", "label": "ヒゲ率上限", "default": 0.05, "type": "choice", "choices": [0.02, 0.05, 0.1]},
    ],
    "gartley_bullish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "gartley_bearish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "bat_bullish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "bat_bearish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "butterfly_bullish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "butterfly_bearish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "crab_bullish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
    "crab_bearish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.1, "type": "choice", "choices": [0.05, 0.1, 0.15]},
    ],
})

# 2026-07-08追加(4巡目)
INDICATOR_PARAM_SPECS.update({
    "ab_cd_bullish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.15, "type": "choice", "choices": [0.1, 0.15, 0.2]},
    ],
    "ab_cd_bearish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.15, "type": "choice", "choices": [0.1, 0.15, 0.2]},
    ],
    "three_drives_bullish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.15, "type": "choice", "choices": [0.1, 0.15, 0.2]},
    ],
    "three_drives_bearish": [
        {"name": "lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "tolerance", "label": "比率許容誤差", "default": 0.15, "type": "choice", "choices": [0.1, 0.15, 0.2]},
    ],
    "uptrend_line_break": [{"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "downtrend_line_break": [{"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "ascending_channel_break": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "slope_tolerance_atr_mult", "label": "傾き一致許容度(ATR倍率)", "default": 0.02, "type": "choice", "choices": [0.01, 0.02, 0.05]},
    ],
    "descending_channel_break": [
        {"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"},
        {"name": "slope_tolerance_atr_mult", "label": "傾き一致許容度(ATR倍率)", "default": 0.02, "type": "choice", "choices": [0.01, 0.02, 0.05]},
    ],
    "false_breakout_bullish_reversal": [
        {"name": "window", "label": "レンジ判定期間", "default": 20, "type": "int"},
        {"name": "box_atr_mult", "label": "ボックス幅上限(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
        {"name": "max_bars_outside", "label": "ブレイク後の戻り許容本数", "default": 3, "type": "int"},
    ],
    "false_breakout_bearish_reversal": [
        {"name": "window", "label": "レンジ判定期間", "default": 20, "type": "int"},
        {"name": "box_atr_mult", "label": "ボックス幅上限(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
        {"name": "max_bars_outside", "label": "ブレイク後の戻り許容本数", "default": 3, "type": "int"},
    ],
    "nr4": [],
    "nr7": [],
    "volume_climax_bullish": [
        {"name": "lookback", "label": "平均算出期間", "default": 20, "type": "int"},
        {"name": "body_mult", "label": "実体倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
        {"name": "volume_mult", "label": "出来高倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
    ],
    "volume_climax_bearish": [
        {"name": "lookback", "label": "平均算出期間", "default": 20, "type": "int"},
        {"name": "body_mult", "label": "実体倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
        {"name": "volume_mult", "label": "出来高倍率", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
    ],
})

# 2026-07-08追加(5巡目、HFM記事の未実装分)
INDICATOR_PARAM_SPECS.update({
    "saucer_top": [{"name": "window", "label": "判定期間", "default": 30, "type": "int"}],
    "saucer_bottom": [{"name": "window", "label": "判定期間", "default": 30, "type": "int"}],
    "ascending_rectangle_breakout": [
        {"name": "window", "label": "レンジ判定期間", "default": 20, "type": "int"},
        {"name": "box_atr_mult", "label": "ボックス幅上限(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
        {"name": "trend_lookback", "label": "事前トレンド判定期間", "default": 30, "type": "int"},
    ],
    "descending_rectangle_breakdown": [
        {"name": "window", "label": "レンジ判定期間", "default": 20, "type": "int"},
        {"name": "box_atr_mult", "label": "ボックス幅上限(ATR倍率)", "default": 2.0, "type": "choice", "choices": [1.5, 2.0, 2.5, 3.0]},
        {"name": "trend_lookback", "label": "事前トレンド判定期間", "default": 30, "type": "int"},
    ],
    "broadening_formation_breakout_bullish": [{"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "broadening_formation_breakout_bearish": [{"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "diamond_formation_breakout_bullish": [{"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "diamond_formation_breakout_bearish": [{"name": "swing_lookback", "label": "スイング判定期間", "default": 5, "type": "int"}],
    "cup_with_handle_breakout": [
        {"name": "cup_window", "label": "カップ判定期間", "default": 40, "type": "int"},
        {"name": "handle_window", "label": "ハンドル判定期間", "default": 10, "type": "int"},
        {"name": "handle_atr_mult", "label": "ハンドル幅上限(ATR倍率)", "default": 1.5, "type": "choice", "choices": [1.0, 1.5, 2.0]},
    ],
})


@app.get("/api/indicators")
async def get_indicators() -> list[dict]:
    return [
        {
            "id": name,
            "label": INDICATOR_LABELS.get(name, name),
            "params": INDICATOR_PARAM_SPECS.get(name, []),
        }
        for name in INDICATOR_REGISTRY
    ]


@app.get("/api/strategies")
async def get_strategies() -> list[dict]:
    return list_strategies()


@app.get("/api/strategies/{strategy_id}")
async def get_strategy_detail(strategy_id: str) -> dict:
    try:
        return get_strategy(strategy_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="strategy not found")


# Serves the built frontend (frontend/dist, produced by `npm run build`) as
# static files - lets this ONE process be the entire app (no separate Vite/
# Node process needed), which is what the packaged one-click launcher runs.
# Mounted LAST so it never shadows the /api/* routes above (Starlette tries
# routes in registration order). Only mounted if the build output actually
# exists - running via `npm run dev` for local development still serves the
# frontend separately on its own Vite dev server (proxying /api to this
# server, see frontend/vite.config.ts), unaffected by this.
_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")


if __name__ == "__main__":
    # Entry point for the packaged launcher (run.bat runs
    # `python.exe api_server.py`) - equivalent to
    # `uvicorn api_server:app --host 127.0.0.1 --port 8736` but doesn't
    # require a separate `uvicorn` command on PATH inside the embeddable
    # Python distribution.
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8736)

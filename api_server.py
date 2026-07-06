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
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
        # Without this, run_backtest()/engine/filters.py silently fall back to
        # pip_size=0.01 (main.py's own default grid always sets this
        # per-symbol, but --strategy-config JSON files don't unless told to) -
        # correct for JPY pairs, but 100x too large for EURUSD/GBPUSD/AUDUSD,
        # silently corrupting every _pips-suffixed filter threshold and the
        # spread/slippage cost above for 3 of the 7 supported symbols.
        "pip_size": [pip_size_for_symbol(req.symbol)],
        "direction": [req.direction],
        "condition_tree": [req.condition_tree],
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


async def _run_job(job_id: str, cmd: list[str]) -> None:
    JOBS[job_id]["status"] = "running"

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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


@app.get("/api/backtests/{job_id}")
async def get_backtest_status(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    return {
        "status": job["status"],
        "stdout_tail": job["stdout"][-2000:],
        "error": job["stderr"][-2000:] if job["status"] == "error" else None,
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
    "hour": "時刻(JST)",
    "weekday": "曜日(0=月〜6=日)",
    "month": "月(1〜12)",
}

INDICATORS_NEEDING_PERIOD = {
    "ema", "sma", "rsi", "atr", "highest_high", "lowest_low", "donchian_mid",
    "adx", "plus_di", "minus_di", "supertrend_line", "supertrend_direction",
    "liquidity_sweep_bullish", "liquidity_sweep_bearish", "bos_bullish", "bos_bearish",
    "choch_bullish", "choch_bearish",
}


@app.get("/api/indicators")
async def get_indicators() -> list[dict]:
    return [
        {
            "id": name,
            "label": INDICATOR_LABELS.get(name, name),
            "needs_period": name in INDICATORS_NEEDING_PERIOD,
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

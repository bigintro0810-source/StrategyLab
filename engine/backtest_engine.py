from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from engine.conditions import evaluate_condition_tree
from engine.indicators import atr as _wilder_atr
from engine.signal_builder import build_candidate_signal


@dataclass
class BacktestConfig:
    ema_length: int = 200
    min_body_pips: float = 20.0
    max_body_pips: float = 0.0
    max_wick_pips: float = 0.0
    lookahead_bars: int = 15
    breakout_bars: int = 30
    ema_distance_pips: float = 50.0
    rsi_min: float = 70.0
    rr: float = 1.2
    session_start: int = 8
    session_end: int = 3
    use_weekend_exit: bool = True
    weekend_exit_hour: int = 4
    use_daily_exit: bool = False
    daily_exit_hour: int = 4
    direction: str = "short"
    # Execution cost simulation - all default to 0.0 (frictionless fills,
    # exactly today's behavior) so existing callers/tests are unaffected
    # unless they opt in.
    spread_pips: float = 0.0
    slippage_pips: float = 0.0
    commission_per_trade: float = 0.0
    # ATR trailing stop - default off (fixed RR-based SL/TP, today's exact
    # behavior). When on, SL trails behind price at atr_trailing_multiplier
    # x ATR, only ever moving in the trade's favor (tighter), never
    # loosening - the existing RR-based TP stays active alongside it, so a
    # trade still exits at whichever of (trailing SL, fixed TP) is hit first.
    use_atr_trailing_stop: bool = False
    atr_trailing_length: int = 14
    atr_trailing_multiplier: float = 2.0
    # Circuit breakers - both default off (never pause, today's exact
    # behavior). Confirmed with the user 2026-07-06: both pause-and-resume
    # rather than stopping permanently. Neither closes an already-open
    # position early - they only block opening NEW ones while paused.
    use_max_dd_stop: bool = False
    max_dd_stop_pips: float = 100.0
    use_consecutive_loss_stop: bool = False
    consecutive_loss_stop_count: int = 3
    consecutive_loss_stop_bars: int = 100
    # Entry order type - "market" (default) is today's exact unchanged
    # behavior (signal candidate -> confirm via close beyond the signal
    # bar's high/low within lookahead_bars -> enter at the NEXT bar's
    # open). "limit"/"stop" skip that close-confirmation step entirely -
    # the instant a candidate signal fires, a pending order is placed at
    # entry_offset_pips away from that bar's close (limit: a better price,
    # against the trade's direction; stop: a worse price, confirming
    # momentum in the trade's direction) and fills at that EXACT price the
    # first time the market touches it within lookahead_bars, or is
    # cancelled if it doesn't.
    entry_method: str = "market"
    entry_offset_pips: float = 10.0
    # Position sizing - default off. When off, "profit"/"net_profit"/etc
    # everywhere stay in raw price-difference units exactly as today
    # (1 lot implied). When on, ADDITIONAL fields are computed alongside
    # the existing ones (lot_size, profit_currency, account_balance per
    # trade) - the existing pip-based profit and every metric derived from
    # it (PF, DD, ranking, etc.) are completely unaffected, so turning
    # this on never changes how strategies compare to each other.
    #
    # Quote currency is inferred from pip_size (0.01 => JPY-quoted,
    # matching JPY_PIP_SIZE below; anything else => USD-quoted) rather
    # than needing the symbol string threaded through the engine, since
    # that 1:1 correspondence already holds throughout this codebase.
    # When account_currency differs from the quote currency, conversion
    # uses a single fixed conversion_rate for the whole backtest (an
    # approximation - not a bar-by-bar historical USDJPY rate) rather than
    # loading a second currency pair's full history through every caller.
    use_position_sizing: bool = False
    position_sizing_method: str = "risk_percent"  # risk_percent | fixed_lot | compounding
    initial_capital: float = 1_000_000.0
    account_currency: str = "JPY"  # JPY | USD
    risk_percent: float = 1.0
    fixed_lot_size: float = 0.1
    contract_size: float = 100_000.0
    conversion_rate: float = 150.0


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's smoothed RSI - matches TradingView's built-in RSI.

    Verified 2026-07-03 against data/raw/TV_USDJPY_15m.csv's exported RSI
    column: this formula agrees with TradingView at 100% of RSI>70 bars
    (mean abs diff 0.006), vs. a simple-rolling-mean version which only
    agreed 90.48% of the time (mean abs diff 6.6) - that version was live
    in this engine until this change and never actually matched
    TradingView despite the project's TradingView-validation goal.
    """
    diff = series.diff()
    gain = diff.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def is_in_session(hour: int, start_hour: int, end_hour: int) -> bool:
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def compute_is_intraday(datetime_series: pd.Series) -> bool:
    bar_seconds = pd.to_datetime(datetime_series).diff().dt.total_seconds().median()

    if pd.isna(bar_seconds):
        return True

    return bool(bar_seconds < 86400)


def calc_max_dd(profits: np.ndarray) -> float:
    if len(profits) == 0:
        return 0.0

    equity = profits.cumsum()
    running_max = np.maximum.accumulate(equity)
    drawdown = running_max - equity

    return float(drawdown.max())


def _pip_value_in_account_currency(
    pip_size: float, contract_size: float, account_currency: str, conversion_rate: float
) -> float:
    """Value of one pip move on one standard lot, expressed in the
    account's currency. Quote currency is inferred from pip_size (0.01 =>
    JPY-quoted, matching JPY_PIP_SIZE in main.py; anything else =>
    USD-quoted) since that correspondence already holds throughout this
    codebase. conversion_rate is a single fixed snapshot for the whole
    backtest when the account currency differs from the quote currency -
    an approximation, not a bar-by-bar historical rate."""
    quote_currency = "JPY" if abs(pip_size - 0.01) < 1e-9 else "USD"
    pip_value_quote = pip_size * contract_size

    if account_currency == quote_currency:
        return pip_value_quote
    if account_currency == "JPY" and quote_currency == "USD":
        return pip_value_quote * conversion_rate
    return pip_value_quote / conversion_rate


def _compute_lot_size(
    method: str,
    risk_percent: float,
    fixed_lot_size: float,
    initial_capital: float,
    account_balance: float,
    sl_distance_pips: float,
    pip_value_account: float,
) -> float:
    if method == "fixed_lot":
        return fixed_lot_size

    # risk_percent always risks a % of the STARTING capital (a fixed pips
    # risked per trade regardless of how the account has grown/shrunk);
    # compounding risks a % of the CURRENT balance (grows/shrinks with it).
    # Clamped at 0 (not the current, possibly negative, balance) - a wiped
    # or negative account can't risk a % of a negative number and get a
    # sane result (that would flip the sign, producing a "negative lot
    # size" that doesn't correspond to any real position).
    base_capital = initial_capital if method == "risk_percent" else max(0.0, account_balance)
    risk_amount = base_capital * (risk_percent / 100.0)

    # The limit/stop entry path derives both the entry price (signal bar's
    # close +/- entry_offset_pips) and the SL (that same signal bar's
    # high/low) from the same candle, so for some candles the two can land
    # a hair's-width apart - not exactly 0 (which the market-order path's
    # >0 check already handles) but small enough that dividing by it
    # produces an absurd multi-trillion-lot position. 0.01 pip is far
    # below any economically meaningful stop distance, so this only catches
    # that degenerate near-zero case, not real (if tight) stop placements.
    if sl_distance_pips <= 0.01 or pip_value_account <= 0:
        return 0.0

    return risk_amount / (sl_distance_pips * pip_value_account)


def prepare_indicator_columns(
    df: pd.DataFrame,
    ema_lengths: list[int] | tuple[int, ...],
    rsi_length: int = 14,
) -> pd.DataFrame:
    work = df.copy()

    for length in sorted(set(int(x) for x in ema_lengths)):
        col = f"ema_{length}"
        if col not in work.columns:
            work[col] = ema(work["close"], length)

    rsi_col = f"rsi_{rsi_length}"
    if rsi_col not in work.columns:
        work[rsi_col] = rsi(work["close"], rsi_length)

    return work


def resolve_ema_series(df: pd.DataFrame, ema_length: int) -> pd.Series:
    cached_col = f"ema_{int(ema_length)}"

    if cached_col in df.columns:
        return pd.to_numeric(df[cached_col], errors="coerce")

    if int(ema_length) == 200 and "EMA200" in df.columns:
        return pd.to_numeric(df["EMA200"], errors="coerce")

    return ema(df["close"], int(ema_length))


def resolve_rsi_series(df: pd.DataFrame, rsi_length: int = 14) -> pd.Series:
    cached_col = f"rsi_{int(rsi_length)}"

    if cached_col in df.columns:
        return pd.to_numeric(df[cached_col], errors="coerce")

    if int(rsi_length) == 14 and "RSI" in df.columns:
        return pd.to_numeric(df["RSI"], errors="coerce")

    return rsi(df["close"], int(rsi_length))


def build_previous_high_array(high_arr: np.ndarray, lookback: int) -> np.ndarray:
    high_series = pd.Series(high_arr)
    return high_series.rolling(window=lookback).max().shift(1).to_numpy(dtype=float)


def build_previous_low_array(low_arr: np.ndarray, lookback: int) -> np.ndarray:
    low_series = pd.Series(low_arr)
    return low_series.rolling(window=lookback).min().shift(1).to_numpy(dtype=float)


def run_backtest(
    df: pd.DataFrame,
    params: dict[str, Any] | BacktestConfig,
    return_trades: bool = False,
    is_intraday: bool | None = None,
) -> dict[str, Any] | tuple[dict[str, Any], pd.DataFrame]:
    if isinstance(params, BacktestConfig):
        p = asdict(params)
    else:
        p = dict(params)

    # Simultaneous Long+Short entry trees (per the dashboard mockup) is a
    # separate, fully additive code path - engaged only when either of these
    # is supplied. Everything below this point is completely unchanged
    # single-direction behavior otherwise, so existing callers/tests are
    # unaffected. See _run_dual_direction_backtest's docstring for the
    # same-bar-collision policy (skip that bar; confirmed with the user
    # rather than assumed, since it changes what a backtest result means).
    entry_method = str(p.get("entry_method", "market")).lower()
    if entry_method not in ("market", "limit", "stop"):
        raise ValueError(f"未対応のentry_methodです(market/limit/stopのみ対応): {entry_method}")

    if p.get("long_condition_tree") is not None or p.get("short_condition_tree") is not None:
        if entry_method != "market":
            raise ValueError(
                "limit/stopエントリーはLong+Short同時評価と組み合わせ未対応です"
                "(どちらか一方のみ指定してください)。"
            )
        return _run_dual_direction_backtest(df, p, return_trades=return_trades, is_intraday=is_intraday)

    if entry_method != "market":
        return _run_limit_stop_backtest(df, p, return_trades=return_trades, is_intraday=is_intraday)

    pip = float(p.get("pip_size", 0.01))

    # Round-trip execution cost, expressed in the same price-difference units
    # as "profit" below (this codebase already calls that unit "pips" without
    # actually dividing by pip_size - matching that existing convention here
    # rather than introducing a second, inconsistent one).
    cost_per_trade = (
        float(p.get("spread_pips", 0.0)) * pip
        + float(p.get("slippage_pips", 0.0)) * pip
        + float(p.get("commission_per_trade", 0.0))
    )

    direction = str(p.get("direction", "short")).lower()
    if direction not in ("short", "long"):
        raise ValueError(f"未対応のdirectionです(short/longのみ対応): {direction}")

    ema_length = int(p["ema_length"])
    lookahead_bars = int(p["lookahead_bars"])
    breakout_bars = int(p["breakout_bars"])
    rr = float(p["rr"])

    use_weekend_exit = bool(p["use_weekend_exit"])
    weekend_exit_hour = int(p["weekend_exit_hour"])

    use_daily_exit = bool(p["use_daily_exit"])
    daily_exit_hour = int(p["daily_exit_hour"])

    datetime_arr = df["datetime"].to_numpy()

    datetime_series = pd.to_datetime(df["datetime"])
    hour_arr = datetime_series.dt.hour.to_numpy(dtype=np.int16)
    weekday_arr = datetime_series.dt.weekday.to_numpy(dtype=np.int16)

    if is_intraday is None:
        is_intraday = compute_is_intraday(datetime_series)

    open_arr = df["open"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)

    ema_arr = resolve_ema_series(df, ema_length).to_numpy(dtype=float)
    rsi_arr = resolve_rsi_series(df, 14).to_numpy(dtype=float)

    use_atr_trailing_stop = bool(p.get("use_atr_trailing_stop", False))
    atr_trailing_multiplier = float(p.get("atr_trailing_multiplier", 2.0))
    atr_trail_arr = (
        _wilder_atr(df, int(p.get("atr_trailing_length", 14))).to_numpy(dtype=float)
        if use_atr_trailing_stop
        else None
    )

    use_max_dd_stop = bool(p.get("use_max_dd_stop", False))
    max_dd_stop_pips = float(p.get("max_dd_stop_pips", 100.0))
    use_consecutive_loss_stop = bool(p.get("use_consecutive_loss_stop", False))
    consecutive_loss_stop_count = int(p.get("consecutive_loss_stop_count", 3))
    consecutive_loss_stop_bars = int(p.get("consecutive_loss_stop_bars", 100))

    use_position_sizing = bool(p.get("use_position_sizing", False))
    position_sizing_method = str(p.get("position_sizing_method", "risk_percent"))
    initial_capital = float(p.get("initial_capital", 1_000_000.0))
    risk_percent = float(p.get("risk_percent", 1.0))
    fixed_lot_size = float(p.get("fixed_lot_size", 0.1))
    pip_value_account = (
        _pip_value_in_account_currency(
            pip,
            float(p.get("contract_size", 100_000.0)),
            str(p.get("account_currency", "JPY")),
            float(p.get("conversion_rate", 150.0)),
        )
        if use_position_sizing
        else 0.0
    )
    account_balance = initial_capital

    previous_high_arr = build_previous_high_array(high_arr, breakout_bars)

    condition_tree = p.get("condition_tree")
    if condition_tree is not None:
        # V-next generic condition engine (engine/conditions.py) - additive path,
        # selected only when a strategy explicitly supplies a condition_tree. The
        # existing entry_trigger/use_X_filter path below is untouched otherwise.
        candidate_signal = evaluate_condition_tree(condition_tree, df)
    else:
        candidate_signal = build_candidate_signal(
            df,
            p,
            {
                "open": open_arr,
                "high": high_arr,
                "low": low_arr,
                "close": close_arr,
                "ema": ema_arr,
                "rsi": rsi_arr,
                "previous_high": previous_high_arr,
                "hour": hour_arr,
                "weekday": weekday_arr,
                "is_intraday": is_intraday,
                "pip": pip,
            },
        )

    profits: list[float] = []
    trade_logs: list[dict[str, Any]] = []

    in_position = False

    entry_price = 0.0
    entry_time = None
    entry_bar_index = None

    sl = 0.0
    tp = 0.0

    signal_low = np.nan
    signal_high = np.nan
    signal_bar = None
    signal_time = None

    pending_entry = False
    pending_signal_low = np.nan
    pending_signal_high = np.nan
    pending_signal_bar = None
    pending_signal_time = None

    position_signal_low = np.nan
    position_signal_high = np.nan
    position_signal_bar = None
    position_signal_time = None

    # Circuit breaker state - only tracked/consulted when the corresponding
    # use_* flag is on, so this is a no-op when both are off.
    cumulative_equity = 0.0
    running_peak_equity = 0.0
    current_dd = 0.0
    paused_for_dd = False
    consecutive_losses = 0
    paused_until_bar: int | None = None

    position_lot_size = 0.0

    for i in range(250, len(df)):
        dt = datetime_arr[i]
        hour = int(hour_arr[i])
        weekday = int(weekday_arr[i])

        entries_blocked = paused_for_dd or (paused_until_bar is not None and i < paused_until_bar)

        open_price = float(open_arr[i])
        high_price = float(high_arr[i])
        low_price = float(low_arr[i])
        close_price = float(close_arr[i])

        if pending_entry and not in_position and not entries_blocked:
            entry_price = open_price
            entry_time = dt
            entry_bar_index = i

            position_signal_low = pending_signal_low
            position_signal_high = pending_signal_high
            position_signal_bar = pending_signal_bar
            position_signal_time = pending_signal_time

            if direction == "short":
                stop_price = float(position_signal_high)
                risk_distance = stop_price - entry_price
            else:
                stop_price = float(position_signal_low)
                risk_distance = entry_price - stop_price

            if risk_distance > 0:
                sl = stop_price
                tp = (
                    entry_price - risk_distance * rr
                    if direction == "short"
                    else entry_price + risk_distance * rr
                )
                in_position = True

                if use_position_sizing:
                    position_lot_size = _compute_lot_size(
                        position_sizing_method,
                        risk_percent,
                        fixed_lot_size,
                        initial_capital,
                        account_balance,
                        risk_distance / pip,
                        pip_value_account,
                    )

            pending_entry = False
            pending_signal_low = np.nan
            pending_signal_high = np.nan
            pending_signal_bar = None
            pending_signal_time = None
        elif pending_entry and not in_position and entries_blocked:
            # A circuit breaker engaged while this signal was waiting to
            # fire - discard it rather than entering on a stale signal
            # once the pause lifts bars (or DD levels) later.
            pending_entry = False
            pending_signal_low = np.nan
            pending_signal_high = np.nan
            pending_signal_bar = None
            pending_signal_time = None

        if in_position:
            # Tighten (never loosen) the stop based on the ATR as of the
            # last CLOSED bar, before checking whether this bar's range
            # hits it - mirrors the entry mechanism's own "confirm on
            # close, act on the next bar" causality, avoiding a look-ahead
            # bias that would come from trailing off this same bar's own
            # close and then immediately checking that bar's high/low
            # against it.
            if use_atr_trailing_stop and i > 0 and not np.isnan(atr_trail_arr[i - 1]):
                trail_distance = atr_trail_arr[i - 1] * atr_trailing_multiplier
                if direction == "short":
                    candidate_sl = close_arr[i - 1] + trail_distance
                    if candidate_sl < sl:
                        sl = candidate_sl
                else:
                    candidate_sl = close_arr[i - 1] - trail_distance
                    if candidate_sl > sl:
                        sl = candidate_sl

            exit_reason = None
            exit_price = None

            if is_intraday and use_weekend_exit and weekday == 5 and hour >= weekend_exit_hour:
                exit_reason = "Weekend"
                exit_price = close_price

            elif is_intraday and use_daily_exit and hour == daily_exit_hour:
                exit_reason = "DailyExit"
                exit_price = close_price

            else:
                if direction == "short":
                    hit_sl = high_price >= sl
                    hit_tp = low_price <= tp
                else:
                    hit_sl = low_price <= sl
                    hit_tp = high_price >= tp

                if hit_sl and hit_tp:
                    exit_reason = "SL_and_TP_SL_first"
                    exit_price = sl
                elif hit_sl:
                    exit_reason = "SL"
                    exit_price = sl
                elif hit_tp:
                    exit_reason = "TP"
                    exit_price = tp

            if exit_reason is not None:
                profit = (
                    entry_price - float(exit_price)
                    if direction == "short"
                    else float(exit_price) - entry_price
                )
                profit -= cost_per_trade
                profits.append(profit)
                cumulative_equity += profit

                if use_max_dd_stop:
                    running_peak_equity = max(running_peak_equity, cumulative_equity)
                    current_dd = running_peak_equity - cumulative_equity
                    if current_dd >= max_dd_stop_pips:
                        paused_for_dd = True
                    elif paused_for_dd and current_dd <= max_dd_stop_pips * 0.5:
                        paused_for_dd = False

                if use_consecutive_loss_stop:
                    if profit < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= consecutive_loss_stop_count:
                            paused_until_bar = i + consecutive_loss_stop_bars
                            consecutive_losses = 0
                    else:
                        consecutive_losses = 0

                profit_currency = None
                if use_position_sizing:
                    profit_currency = (profit / pip) * pip_value_account * position_lot_size
                    account_balance += profit_currency

                if return_trades:
                    trade_logs.append(
                        {
                            "entry_time": entry_time,
                            "entry_bar_index": entry_bar_index,
                            "entry_price": round(entry_price, 5),
                            "exit_time": dt,
                            "exit_bar_index": i,
                            "exit_price": round(float(exit_price), 5),
                            "sl": round(sl, 5),
                            "tp": round(tp, 5),
                            "profit": round(profit, 5),
                            "exit_reason": exit_reason,
                            "signal_time": position_signal_time,
                            "signal_bar_index": position_signal_bar,
                            "signal_low": round(float(position_signal_low), 5),
                            "signal_high": round(float(position_signal_high), 5),
                            **(
                                {
                                    "lot_size": round(position_lot_size, 4),
                                    "profit_currency": round(profit_currency, 2),
                                    "account_balance": round(account_balance, 2),
                                }
                                if use_position_sizing
                                else {}
                            ),
                        }
                    )

                in_position = False

                entry_price = 0.0
                entry_time = None
                entry_bar_index = None

                sl = 0.0
                tp = 0.0

                position_signal_low = np.nan
                position_signal_high = np.nan
                position_signal_bar = None
                position_signal_time = None

            continue

        if entries_blocked:
            # A circuit breaker is active - don't track or confirm any new
            # candidate signal while paused. Whatever was already being
            # tracked (signal_bar) isn't touched here, but its elapsed-bar
            # count keeps advancing in the background, so by the time the
            # pause lifts it will very likely read as expired (matching
            # how a stale signal already expires if bypassed while
            # in_position elsewhere in this loop) rather than resuming a
            # confirmation window based on years-old price levels.
            continue

        if signal_bar is not None:
            bars_from_signal = i - signal_bar
            within_bars = bars_from_signal > 0 and bars_from_signal <= lookahead_bars

            confirmation = (
                close_price < float(signal_low)
                if direction == "short"
                else close_price > float(signal_high)
            )
            if within_bars and confirmation:
                pending_entry = True

                pending_signal_low = signal_low
                pending_signal_high = signal_high
                pending_signal_bar = signal_bar
                pending_signal_time = signal_time

                signal_low = np.nan
                signal_high = np.nan
                signal_bar = None
                signal_time = None

                continue

            expired = bars_from_signal > lookahead_bars
            if expired:
                signal_low = np.nan
                signal_high = np.nan
                signal_bar = None
                signal_time = None

        if signal_bar is not None:
            continue

        if not candidate_signal[i]:
            continue

        signal_low = low_price
        signal_high = high_price
        signal_bar = i
        signal_time = dt

    profits_arr = np.array(profits, dtype=float)

    trades = int(len(profits_arr))
    wins = int((profits_arr > 0).sum())
    losses = int((profits_arr < 0).sum())

    gross_profit = float(profits_arr[profits_arr > 0].sum()) if trades else 0.0
    gross_loss = float(profits_arr[profits_arr < 0].sum()) if trades else 0.0
    net_profit = float(profits_arr.sum()) if trades else 0.0

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    win_rate = wins / trades * 100.0 if trades else 0.0
    max_dd = calc_max_dd(profits_arr)
    expected_value = net_profit / trades if trades else 0.0

    if max_dd > 0:
        recovery_factor = net_profit / max_dd
    elif net_profit > 0:
        recovery_factor = 999.0
    else:
        recovery_factor = 0.0

    result = {
        **p,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "net_profit": round(net_profit, 5),
        "gross_profit": round(gross_profit, 5),
        "gross_loss": round(gross_loss, 5),
        "profit_factor": round(profit_factor, 3),
        "max_dd": round(max_dd, 5),
        "expected_value": round(expected_value, 5),
        "recovery_factor": round(recovery_factor, 3),
        **(
            {
                "final_account_balance": round(account_balance, 2),
                "total_profit_currency": round(account_balance - initial_capital, 2),
            }
            if use_position_sizing
            else {}
        ),
    }

    trades_df = pd.DataFrame(trade_logs)

    if return_trades:
        return result, trades_df

    return result


def _run_limit_stop_backtest(
    df: pd.DataFrame,
    p: dict[str, Any],
    return_trades: bool = False,
    is_intraday: bool | None = None,
) -> dict[str, Any] | tuple[dict[str, Any], pd.DataFrame]:
    """entry_method="limit" or "stop" - a separate code path from
    run_backtest()'s market-order state machine (signal -> confirm via
    close beyond the signal bar's high/low -> enter at the next bar's
    open), engaged only when entry_method is set to something other than
    "market". Single-direction only for now - combining with the
    simultaneous Long+Short dual-direction path is rejected with a clear
    error in run_backtest() rather than silently ignored.

    The instant a candidate signal fires, a pending order is placed at
    entry_offset_pips away from that bar's close - "limit" places it at a
    BETTER price (against the trade's direction, a pullback-style entry),
    "stop" places it at a WORSE price (with the trade's direction,
    confirming momentum before entering). The order fills at that EXACT
    price the first time the market touches it on a LATER bar (never the
    same bar it was placed on, to avoid using that bar's own close to set
    a price and then immediately checking that same bar's range against
    it), or is cancelled if lookahead_bars pass without a fill.

    SL/TP once filled are computed exactly as run_backtest() does -
    RR-based off the candidate signal bar's high/low - and everything
    orthogonal (ATR trailing stop, circuit breakers, execution cost) is
    identical to run_backtest(), just layered onto this different entry
    mechanism.
    """
    pip = float(p.get("pip_size", 0.01))

    cost_per_trade = (
        float(p.get("spread_pips", 0.0)) * pip
        + float(p.get("slippage_pips", 0.0)) * pip
        + float(p.get("commission_per_trade", 0.0))
    )

    direction = str(p.get("direction", "short")).lower()
    if direction not in ("short", "long"):
        raise ValueError(f"未対応のdirectionです(short/longのみ対応): {direction}")

    entry_method = str(p.get("entry_method", "market")).lower()
    entry_offset = float(p.get("entry_offset_pips", 10.0)) * pip

    lookahead_bars = int(p["lookahead_bars"])
    rr = float(p["rr"])

    use_weekend_exit = bool(p["use_weekend_exit"])
    weekend_exit_hour = int(p["weekend_exit_hour"])

    use_daily_exit = bool(p["use_daily_exit"])
    daily_exit_hour = int(p["daily_exit_hour"])

    datetime_arr = df["datetime"].to_numpy()

    datetime_series = pd.to_datetime(df["datetime"])
    hour_arr = datetime_series.dt.hour.to_numpy(dtype=np.int16)
    weekday_arr = datetime_series.dt.weekday.to_numpy(dtype=np.int16)

    if is_intraday is None:
        is_intraday = compute_is_intraday(datetime_series)

    open_arr = df["open"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)

    use_atr_trailing_stop = bool(p.get("use_atr_trailing_stop", False))
    atr_trailing_multiplier = float(p.get("atr_trailing_multiplier", 2.0))
    atr_trail_arr = (
        _wilder_atr(df, int(p.get("atr_trailing_length", 14))).to_numpy(dtype=float)
        if use_atr_trailing_stop
        else None
    )

    use_max_dd_stop = bool(p.get("use_max_dd_stop", False))
    max_dd_stop_pips = float(p.get("max_dd_stop_pips", 100.0))
    use_consecutive_loss_stop = bool(p.get("use_consecutive_loss_stop", False))
    consecutive_loss_stop_count = int(p.get("consecutive_loss_stop_count", 3))
    consecutive_loss_stop_bars = int(p.get("consecutive_loss_stop_bars", 100))

    use_position_sizing = bool(p.get("use_position_sizing", False))
    position_sizing_method = str(p.get("position_sizing_method", "risk_percent"))
    initial_capital = float(p.get("initial_capital", 1_000_000.0))
    risk_percent = float(p.get("risk_percent", 1.0))
    fixed_lot_size = float(p.get("fixed_lot_size", 0.1))
    pip_value_account = (
        _pip_value_in_account_currency(
            pip,
            float(p.get("contract_size", 100_000.0)),
            str(p.get("account_currency", "JPY")),
            float(p.get("conversion_rate", 150.0)),
        )
        if use_position_sizing
        else 0.0
    )
    account_balance = initial_capital

    condition_tree = p.get("condition_tree")
    if condition_tree is not None:
        candidate_signal = evaluate_condition_tree(condition_tree, df)
    else:
        ema_length = int(p["ema_length"])
        breakout_bars = int(p["breakout_bars"])
        ema_arr = resolve_ema_series(df, ema_length).to_numpy(dtype=float)
        rsi_arr = resolve_rsi_series(df, 14).to_numpy(dtype=float)
        previous_high_arr = build_previous_high_array(high_arr, breakout_bars)
        candidate_signal = build_candidate_signal(
            df,
            p,
            {
                "open": open_arr,
                "high": high_arr,
                "low": low_arr,
                "close": close_arr,
                "ema": ema_arr,
                "rsi": rsi_arr,
                "previous_high": previous_high_arr,
                "hour": hour_arr,
                "weekday": weekday_arr,
                "is_intraday": is_intraday,
                "pip": pip,
            },
        )

    # An order priced ABOVE the market at placement time fills when price
    # rises to meet it (checked via that bar's high); one priced BELOW
    # fills when price falls to meet it (checked via low). A short-limit
    # (sell higher) and a long-stop (buy on further strength) are both
    # "above market" orders; a short-stop and a long-limit are both
    # "below market" orders.
    order_above_market = (direction == "short" and entry_method == "limit") or (
        direction == "long" and entry_method == "stop"
    )

    profits: list[float] = []
    trade_logs: list[dict[str, Any]] = []

    in_position = False

    entry_price = 0.0
    entry_time = None
    entry_bar_index = None

    sl = 0.0
    tp = 0.0

    order_active = False
    order_price = 0.0
    order_bar: int | None = None
    order_signal_low = np.nan
    order_signal_high = np.nan
    order_signal_time = None

    position_signal_low = np.nan
    position_signal_high = np.nan
    position_signal_bar = None
    position_signal_time = None

    cumulative_equity = 0.0
    running_peak_equity = 0.0
    current_dd = 0.0
    paused_for_dd = False
    consecutive_losses = 0
    paused_until_bar: int | None = None
    position_lot_size = 0.0

    for i in range(250, len(df)):
        dt = datetime_arr[i]
        hour = int(hour_arr[i])
        weekday = int(weekday_arr[i])

        entries_blocked = paused_for_dd or (paused_until_bar is not None and i < paused_until_bar)

        open_price = float(open_arr[i])
        high_price = float(high_arr[i])
        low_price = float(low_arr[i])
        close_price = float(close_arr[i])

        if order_active and not in_position:
            if entries_blocked:
                order_active = False
            else:
                bars_since_order = i - order_bar
                if bars_since_order > lookahead_bars:
                    order_active = False
                else:
                    filled = high_price >= order_price if order_above_market else low_price <= order_price
                    if filled:
                        entry_price = order_price
                        entry_time = dt
                        entry_bar_index = i

                        position_signal_low = order_signal_low
                        position_signal_high = order_signal_high
                        position_signal_bar = order_bar
                        position_signal_time = order_signal_time

                        if direction == "short":
                            stop_price = float(position_signal_high)
                            risk_distance = stop_price - entry_price
                        else:
                            stop_price = float(position_signal_low)
                            risk_distance = entry_price - stop_price

                        if risk_distance > 0:
                            sl = stop_price
                            tp = (
                                entry_price - risk_distance * rr
                                if direction == "short"
                                else entry_price + risk_distance * rr
                            )
                            in_position = True

                            if use_position_sizing:
                                position_lot_size = _compute_lot_size(
                                    position_sizing_method,
                                    risk_percent,
                                    fixed_lot_size,
                                    initial_capital,
                                    account_balance,
                                    risk_distance / pip,
                                    pip_value_account,
                                )

                        order_active = False

        if in_position:
            if use_atr_trailing_stop and i > 0 and not np.isnan(atr_trail_arr[i - 1]):
                trail_distance = atr_trail_arr[i - 1] * atr_trailing_multiplier
                if direction == "short":
                    candidate_sl = close_arr[i - 1] + trail_distance
                    if candidate_sl < sl:
                        sl = candidate_sl
                else:
                    candidate_sl = close_arr[i - 1] - trail_distance
                    if candidate_sl > sl:
                        sl = candidate_sl

            exit_reason = None
            exit_price = None

            if is_intraday and use_weekend_exit and weekday == 5 and hour >= weekend_exit_hour:
                exit_reason = "Weekend"
                exit_price = close_price

            elif is_intraday and use_daily_exit and hour == daily_exit_hour:
                exit_reason = "DailyExit"
                exit_price = close_price

            else:
                if direction == "short":
                    hit_sl = high_price >= sl
                    hit_tp = low_price <= tp
                else:
                    hit_sl = low_price <= sl
                    hit_tp = high_price >= tp

                if hit_sl and hit_tp:
                    exit_reason = "SL_and_TP_SL_first"
                    exit_price = sl
                elif hit_sl:
                    exit_reason = "SL"
                    exit_price = sl
                elif hit_tp:
                    exit_reason = "TP"
                    exit_price = tp

            if exit_reason is not None:
                profit = (
                    entry_price - float(exit_price)
                    if direction == "short"
                    else float(exit_price) - entry_price
                )
                profit -= cost_per_trade
                profits.append(profit)
                cumulative_equity += profit

                if use_max_dd_stop:
                    running_peak_equity = max(running_peak_equity, cumulative_equity)
                    current_dd = running_peak_equity - cumulative_equity
                    if current_dd >= max_dd_stop_pips:
                        paused_for_dd = True
                    elif paused_for_dd and current_dd <= max_dd_stop_pips * 0.5:
                        paused_for_dd = False

                if use_consecutive_loss_stop:
                    if profit < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= consecutive_loss_stop_count:
                            paused_until_bar = i + consecutive_loss_stop_bars
                            consecutive_losses = 0
                    else:
                        consecutive_losses = 0

                profit_currency = None
                if use_position_sizing:
                    profit_currency = (profit / pip) * pip_value_account * position_lot_size
                    account_balance += profit_currency

                if return_trades:
                    trade_logs.append(
                        {
                            "entry_time": entry_time,
                            "entry_bar_index": entry_bar_index,
                            "entry_price": round(entry_price, 5),
                            "exit_time": dt,
                            "exit_bar_index": i,
                            "exit_price": round(float(exit_price), 5),
                            "sl": round(sl, 5),
                            "tp": round(tp, 5),
                            "profit": round(profit, 5),
                            "exit_reason": exit_reason,
                            "signal_time": position_signal_time,
                            "signal_bar_index": position_signal_bar,
                            "signal_low": round(float(position_signal_low), 5),
                            "signal_high": round(float(position_signal_high), 5),
                            **(
                                {
                                    "lot_size": round(position_lot_size, 4),
                                    "profit_currency": round(profit_currency, 2),
                                    "account_balance": round(account_balance, 2),
                                }
                                if use_position_sizing
                                else {}
                            ),
                        }
                    )

                in_position = False

                entry_price = 0.0
                entry_time = None
                entry_bar_index = None

                sl = 0.0
                tp = 0.0

                position_signal_low = np.nan
                position_signal_high = np.nan
                position_signal_bar = None
                position_signal_time = None

            continue

        if entries_blocked or order_active:
            continue

        if not candidate_signal[i]:
            continue

        order_price = close_price + entry_offset if order_above_market else close_price - entry_offset
        order_bar = i
        order_signal_low = low_price
        order_signal_high = high_price
        order_signal_time = dt
        order_active = True

    profits_arr = np.array(profits, dtype=float)

    trades = int(len(profits_arr))
    wins = int((profits_arr > 0).sum())
    losses = int((profits_arr < 0).sum())

    gross_profit = float(profits_arr[profits_arr > 0].sum()) if trades else 0.0
    gross_loss = float(profits_arr[profits_arr < 0].sum()) if trades else 0.0
    net_profit = float(profits_arr.sum()) if trades else 0.0

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    win_rate = wins / trades * 100.0 if trades else 0.0
    max_dd = calc_max_dd(profits_arr)
    expected_value = net_profit / trades if trades else 0.0

    if max_dd > 0:
        recovery_factor = net_profit / max_dd
    elif net_profit > 0:
        recovery_factor = 999.0
    else:
        recovery_factor = 0.0

    result = {
        **p,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "net_profit": round(net_profit, 5),
        "gross_profit": round(gross_profit, 5),
        "gross_loss": round(gross_loss, 5),
        "profit_factor": round(profit_factor, 3),
        "max_dd": round(max_dd, 5),
        "expected_value": round(expected_value, 5),
        "recovery_factor": round(recovery_factor, 3),
        **(
            {
                "final_account_balance": round(account_balance, 2),
                "total_profit_currency": round(account_balance - initial_capital, 2),
            }
            if use_position_sizing
            else {}
        ),
    }

    trades_df = pd.DataFrame(trade_logs)

    if return_trades:
        return result, trades_df

    return result


def _run_dual_direction_backtest(
    df: pd.DataFrame,
    p: dict[str, Any],
    return_trades: bool = False,
    is_intraday: bool | None = None,
) -> dict[str, Any] | tuple[dict[str, Any], pd.DataFrame]:
    """Long and Short entry trees evaluated in the same backtest, sharing one
    position slot (no hedging - that's an explicit, separate scope decision
    still pending). Confirmed with the user 2026-07-06: if both a Long and a
    Short entry would fire in the same bar, take neither and wait ("skip that
    bar") rather than picking one arbitrarily.

    Mirrors run_backtest()'s single-direction state machine (signal candidate
    -> confirmation within lookahead_bars -> pending -> next-bar-open entry
    -> SL/TP/time exit) but runs two independent copies of the signal/
    confirmation tracking (one per direction) against one shared in-position
    gate, since only one of them can ever hold the position at a time.
    """
    pip = float(p.get("pip_size", 0.01))

    cost_per_trade = (
        float(p.get("spread_pips", 0.0)) * pip
        + float(p.get("slippage_pips", 0.0)) * pip
        + float(p.get("commission_per_trade", 0.0))
    )

    lookahead_bars = int(p["lookahead_bars"])
    rr = float(p["rr"])

    use_weekend_exit = bool(p["use_weekend_exit"])
    weekend_exit_hour = int(p["weekend_exit_hour"])

    use_daily_exit = bool(p["use_daily_exit"])
    daily_exit_hour = int(p["daily_exit_hour"])

    datetime_arr = df["datetime"].to_numpy()

    datetime_series = pd.to_datetime(df["datetime"])
    hour_arr = datetime_series.dt.hour.to_numpy(dtype=np.int16)
    weekday_arr = datetime_series.dt.weekday.to_numpy(dtype=np.int16)

    if is_intraday is None:
        is_intraday = compute_is_intraday(datetime_series)

    open_arr = df["open"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)

    use_atr_trailing_stop = bool(p.get("use_atr_trailing_stop", False))
    atr_trailing_multiplier = float(p.get("atr_trailing_multiplier", 2.0))
    atr_trail_arr = (
        _wilder_atr(df, int(p.get("atr_trailing_length", 14))).to_numpy(dtype=float)
        if use_atr_trailing_stop
        else None
    )

    use_max_dd_stop = bool(p.get("use_max_dd_stop", False))
    max_dd_stop_pips = float(p.get("max_dd_stop_pips", 100.0))
    use_consecutive_loss_stop = bool(p.get("use_consecutive_loss_stop", False))
    consecutive_loss_stop_count = int(p.get("consecutive_loss_stop_count", 3))
    consecutive_loss_stop_bars = int(p.get("consecutive_loss_stop_bars", 100))

    use_position_sizing = bool(p.get("use_position_sizing", False))
    position_sizing_method = str(p.get("position_sizing_method", "risk_percent"))
    initial_capital = float(p.get("initial_capital", 1_000_000.0))
    risk_percent = float(p.get("risk_percent", 1.0))
    fixed_lot_size = float(p.get("fixed_lot_size", 0.1))
    pip_value_account = (
        _pip_value_in_account_currency(
            pip,
            float(p.get("contract_size", 100_000.0)),
            str(p.get("account_currency", "JPY")),
            float(p.get("conversion_rate", 150.0)),
        )
        if use_position_sizing
        else 0.0
    )
    account_balance = initial_capital

    long_tree = p.get("long_condition_tree")
    short_tree = p.get("short_condition_tree")
    long_candidate = evaluate_condition_tree(long_tree, df) if long_tree is not None else np.zeros(len(df), dtype=bool)
    short_candidate = (
        evaluate_condition_tree(short_tree, df) if short_tree is not None else np.zeros(len(df), dtype=bool)
    )

    profits: list[float] = []
    trade_logs: list[dict[str, Any]] = []

    in_position = False
    position_direction = None

    entry_price = 0.0
    entry_time = None
    entry_bar_index = None

    sl = 0.0
    tp = 0.0

    position_signal_low = np.nan
    position_signal_high = np.nan
    position_signal_bar = None
    position_signal_time = None

    # Per-direction signal/confirmation/pending tracking - each side is an
    # independent copy of run_backtest()'s single-direction state.
    side_state = {
        "long": {
            "signal_low": np.nan,
            "signal_high": np.nan,
            "signal_bar": None,
            "signal_time": None,
            "pending_entry": False,
            "pending_signal_low": np.nan,
            "pending_signal_high": np.nan,
            "pending_signal_bar": None,
            "pending_signal_time": None,
        },
        "short": {
            "signal_low": np.nan,
            "signal_high": np.nan,
            "signal_bar": None,
            "signal_time": None,
            "pending_entry": False,
            "pending_signal_low": np.nan,
            "pending_signal_high": np.nan,
            "pending_signal_bar": None,
            "pending_signal_time": None,
        },
    }

    def clear_pending(side: str) -> None:
        state = side_state[side]
        state["pending_entry"] = False
        state["pending_signal_low"] = np.nan
        state["pending_signal_high"] = np.nan
        state["pending_signal_bar"] = None
        state["pending_signal_time"] = None

    def clear_signal(side: str) -> None:
        state = side_state[side]
        state["signal_low"] = np.nan
        state["signal_high"] = np.nan
        state["signal_bar"] = None
        state["signal_time"] = None

    # Circuit breaker state - only tracked/consulted when the corresponding
    # use_* flag is on, so this is a no-op when both are off.
    cumulative_equity = 0.0
    running_peak_equity = 0.0
    current_dd = 0.0
    paused_for_dd = False
    consecutive_losses = 0
    paused_until_bar: int | None = None
    position_lot_size = 0.0

    for i in range(250, len(df)):
        dt = datetime_arr[i]
        hour = int(hour_arr[i])
        weekday = int(weekday_arr[i])

        entries_blocked = paused_for_dd or (paused_until_bar is not None and i < paused_until_bar)

        open_price = float(open_arr[i])
        high_price = float(high_arr[i])
        low_price = float(low_arr[i])
        close_price = float(close_arr[i])

        if not in_position and not entries_blocked:
            long_ready = side_state["long"]["pending_entry"]
            short_ready = side_state["short"]["pending_entry"]

            if long_ready and short_ready:
                # Both sides confirmed on the same bar - take neither.
                clear_pending("long")
                clear_pending("short")
            elif long_ready or short_ready:
                side = "long" if long_ready else "short"
                state = side_state[side]

                entry_price = open_price
                entry_time = dt
                entry_bar_index = i
                position_direction = side

                position_signal_low = state["pending_signal_low"]
                position_signal_high = state["pending_signal_high"]
                position_signal_bar = state["pending_signal_bar"]
                position_signal_time = state["pending_signal_time"]

                if side == "short":
                    stop_price = float(position_signal_high)
                    risk_distance = stop_price - entry_price
                else:
                    stop_price = float(position_signal_low)
                    risk_distance = entry_price - stop_price

                if risk_distance > 0:
                    sl = stop_price
                    tp = (
                        entry_price - risk_distance * rr
                        if side == "short"
                        else entry_price + risk_distance * rr
                    )
                    in_position = True

                    if use_position_sizing:
                        position_lot_size = _compute_lot_size(
                            position_sizing_method,
                            risk_percent,
                            fixed_lot_size,
                            initial_capital,
                            account_balance,
                            risk_distance / pip,
                            pip_value_account,
                        )

                clear_pending(side)
        elif not in_position and entries_blocked:
            # A circuit breaker engaged while a signal was waiting to fire
            # on either side - discard both rather than entering on a
            # stale signal once the pause lifts.
            clear_pending("long")
            clear_pending("short")

        if in_position:
            if use_atr_trailing_stop and i > 0 and not np.isnan(atr_trail_arr[i - 1]):
                trail_distance = atr_trail_arr[i - 1] * atr_trailing_multiplier
                if position_direction == "short":
                    candidate_sl = close_arr[i - 1] + trail_distance
                    if candidate_sl < sl:
                        sl = candidate_sl
                else:
                    candidate_sl = close_arr[i - 1] - trail_distance
                    if candidate_sl > sl:
                        sl = candidate_sl

            exit_reason = None
            exit_price = None

            if is_intraday and use_weekend_exit and weekday == 5 and hour >= weekend_exit_hour:
                exit_reason = "Weekend"
                exit_price = close_price

            elif is_intraday and use_daily_exit and hour == daily_exit_hour:
                exit_reason = "DailyExit"
                exit_price = close_price

            else:
                if position_direction == "short":
                    hit_sl = high_price >= sl
                    hit_tp = low_price <= tp
                else:
                    hit_sl = low_price <= sl
                    hit_tp = high_price >= tp

                if hit_sl and hit_tp:
                    exit_reason = "SL_and_TP_SL_first"
                    exit_price = sl
                elif hit_sl:
                    exit_reason = "SL"
                    exit_price = sl
                elif hit_tp:
                    exit_reason = "TP"
                    exit_price = tp

            if exit_reason is not None:
                profit = (
                    entry_price - float(exit_price)
                    if position_direction == "short"
                    else float(exit_price) - entry_price
                )
                profit -= cost_per_trade
                profits.append(profit)
                cumulative_equity += profit

                if use_max_dd_stop:
                    running_peak_equity = max(running_peak_equity, cumulative_equity)
                    current_dd = running_peak_equity - cumulative_equity
                    if current_dd >= max_dd_stop_pips:
                        paused_for_dd = True
                    elif paused_for_dd and current_dd <= max_dd_stop_pips * 0.5:
                        paused_for_dd = False

                if use_consecutive_loss_stop:
                    if profit < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= consecutive_loss_stop_count:
                            paused_until_bar = i + consecutive_loss_stop_bars
                            consecutive_losses = 0
                    else:
                        consecutive_losses = 0

                profit_currency = None
                if use_position_sizing:
                    profit_currency = (profit / pip) * pip_value_account * position_lot_size
                    account_balance += profit_currency

                if return_trades:
                    trade_logs.append(
                        {
                            "entry_time": entry_time,
                            "entry_bar_index": entry_bar_index,
                            "entry_price": round(entry_price, 5),
                            "direction": position_direction,
                            "exit_time": dt,
                            "exit_bar_index": i,
                            "exit_price": round(float(exit_price), 5),
                            "sl": round(sl, 5),
                            "tp": round(tp, 5),
                            "profit": round(profit, 5),
                            "exit_reason": exit_reason,
                            "signal_time": position_signal_time,
                            "signal_bar_index": position_signal_bar,
                            "signal_low": round(float(position_signal_low), 5),
                            "signal_high": round(float(position_signal_high), 5),
                            **(
                                {
                                    "lot_size": round(position_lot_size, 4),
                                    "profit_currency": round(profit_currency, 2),
                                    "account_balance": round(account_balance, 2),
                                }
                                if use_position_sizing
                                else {}
                            ),
                        }
                    )

                in_position = False
                position_direction = None

                entry_price = 0.0
                entry_time = None
                entry_bar_index = None

                sl = 0.0
                tp = 0.0

                position_signal_low = np.nan
                position_signal_high = np.nan
                position_signal_bar = None
                position_signal_time = None

            continue

        if entries_blocked:
            # See the single-direction run_backtest()'s identical guard for
            # why this doesn't need to actively freeze signal_bar - it just
            # naturally reads as expired once the pause lifts.
            continue

        for side, candidate_signal in (("long", long_candidate), ("short", short_candidate)):
            state = side_state[side]

            if state["signal_bar"] is not None:
                bars_from_signal = i - state["signal_bar"]
                within_bars = bars_from_signal > 0 and bars_from_signal <= lookahead_bars

                confirmation = (
                    close_price < float(state["signal_low"])
                    if side == "short"
                    else close_price > float(state["signal_high"])
                )
                if within_bars and confirmation:
                    state["pending_entry"] = True
                    state["pending_signal_low"] = state["signal_low"]
                    state["pending_signal_high"] = state["signal_high"]
                    state["pending_signal_bar"] = state["signal_bar"]
                    state["pending_signal_time"] = state["signal_time"]
                    clear_signal(side)
                    continue

                expired = bars_from_signal > lookahead_bars
                if expired:
                    clear_signal(side)

            if state["signal_bar"] is not None:
                continue

            if not candidate_signal[i]:
                continue

            state["signal_low"] = low_price
            state["signal_high"] = high_price
            state["signal_bar"] = i
            state["signal_time"] = dt

    profits_arr = np.array(profits, dtype=float)

    trades = int(len(profits_arr))
    wins = int((profits_arr > 0).sum())
    losses = int((profits_arr < 0).sum())

    gross_profit = float(profits_arr[profits_arr > 0].sum()) if trades else 0.0
    gross_loss = float(profits_arr[profits_arr < 0].sum()) if trades else 0.0
    net_profit = float(profits_arr.sum()) if trades else 0.0

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = 999.0
    else:
        profit_factor = 0.0

    win_rate = wins / trades * 100.0 if trades else 0.0
    max_dd = calc_max_dd(profits_arr)
    expected_value = net_profit / trades if trades else 0.0

    if max_dd > 0:
        recovery_factor = net_profit / max_dd
    elif net_profit > 0:
        recovery_factor = 999.0
    else:
        recovery_factor = 0.0

    result = {
        **p,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "net_profit": round(net_profit, 5),
        "gross_profit": round(gross_profit, 5),
        "gross_loss": round(gross_loss, 5),
        "profit_factor": round(profit_factor, 3),
        "max_dd": round(max_dd, 5),
        "expected_value": round(expected_value, 5),
        "recovery_factor": round(recovery_factor, 3),
        **(
            {
                "final_account_balance": round(account_balance, 2),
                "total_profit_currency": round(account_balance - initial_capital, 2),
            }
            if use_position_sizing
            else {}
        ),
    }

    trades_df = pd.DataFrame(trade_logs)

    if return_trades:
        return result, trades_df

    return result
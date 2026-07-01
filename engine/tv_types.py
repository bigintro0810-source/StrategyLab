from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    MARKET = "market"
    STOP = "stop"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


class ExitReason(str, Enum):
    SL = "SL"
    TP = "TP"
    WEEKEND = "Weekend"
    DAILY_EXIT = "DailyExit"
    CLOSE_ALL = "CloseAll"


@dataclass
class Signal:
    signal_time: datetime
    signal_bar_index: int
    signal_low: float
    signal_high: float
    side: OrderSide


@dataclass
class Order:
    order_id: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    created_time: datetime
    created_bar_index: int
    fill_time: datetime | None = None
    fill_bar_index: int | None = None
    fill_price: float | None = None


@dataclass
class Position:
    side: OrderSide
    entry_time: datetime
    entry_bar_index: int
    entry_price: float
    size: float
    stop_price: float
    limit_price: float
    signal: Signal


@dataclass
class Trade:
    side: OrderSide
    entry_time: datetime
    entry_bar_index: int
    entry_price: float
    exit_time: datetime
    exit_bar_index: int
    exit_price: float
    stop_price: float
    limit_price: float
    profit: float
    exit_reason: ExitReason
    signal_time: datetime
    signal_bar_index: int
    signal_low: float
    signal_high: float
import pandas as pd


def close_above(data: pd.DataFrame, i: int, column: str) -> bool:
    return data.iloc[i]["close"] > data.iloc[i][column]


def close_below(data: pd.DataFrame, i: int, column: str) -> bool:
    return data.iloc[i]["close"] < data.iloc[i][column]


def rsi_above(data: pd.DataFrame, i: int, column: str, value: float) -> bool:
    return data.iloc[i][column] > value


def rsi_below(data: pd.DataFrame, i: int, column: str, value: float) -> bool:
    return data.iloc[i][column] < value


def all_conditions(conditions: list[bool]) -> bool:
    return all(conditions)


def any_conditions(conditions: list[bool]) -> bool:
    return any(conditions)
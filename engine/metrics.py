import pandas as pd


def calculate_metrics(trades):

    if len(trades) == 0:
        return {}

    profits = [t.profit for t in trades]

    total = sum(profits)

    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    win_rate = len(wins) / len(profits) * 100

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    pf = gross_profit / gross_loss if gross_loss != 0 else 999

    return {
        "Trades": len(profits),
        "WinRate": round(win_rate, 2),
        "PF": round(pf, 2),
        "NetProfit": round(total, 2),
    }
# TradingView Order Execution Rules
Version: 1.0

---

# 目的

Strategy Lab のバックテストエンジンで、TradingView Pine Script の `strategy()` に近い注文処理を再現する。

この文書は「戦略条件」ではなく、注文・約定・決済のルールだけを定義する。

---

# 基本原則

戦略ロジックと注文処理を分離する。

Strategy は Signal を生成する。

Engine は以下だけを担当する。

- Order作成
- Order保持
- 約定判定
- Position管理
- Exit管理
- TradeLog生成

---

# Market Entry

Pine Script の `strategy.entry()` は、通常設定では条件成立バーの次バー始値で約定する。

Strategy Lab では以下のように扱う。

```text
Bar N
entry condition true
↓
Market Order Pending
↓
Bar N+1 open
Position Open
```

---

# Entry Price

Market Entry の約定価格は次バーの Open。

```text
entry_price = open[N+1]
```

---

# Exit Order

Pine Script の `strategy.exit()` は、ポジション保有中に stop / limit 注文を管理する。

Strategy Lab では、ポジション約定後に以下を設定する。

```text
stop_price
limit_price
```

Shortの場合

```text
stop_price > entry_price
limit_price < entry_price
```

Longの場合

```text
stop_price < entry_price
limit_price > entry_price
```

---

# Short Exit判定

Short Position の場合

```text
SL hit:
high >= stop_price

TP hit:
low <= limit_price
```

---

# Long Exit判定

Long Position の場合

```text
SL hit:
low <= stop_price

TP hit:
high >= limit_price
```

---

# Same Bar SL/TP Conflict

同一バーでSLとTPの両方に到達した場合は、最初は保守的にSL優先とする。

```text
if hit_sl and hit_tp:
    exit_reason = SL
```

ただし、TradingViewとの差が残る場合は以下を検証する。

- SL優先
- TP優先
- Openに近い方優先
- バー方向順
  - 陽線: open → low → high → close
  - 陰線: open → high → low → close

---

# Close All

`strategy.close_all()` は成行決済として扱う。

発生バーの close で決済する。

```text
exit_price = close[current_bar]
```

---

# Weekend Exit

この戦略では、週末決済は Asia/Tokyo 基準。

```text
dayofweek == Saturday
hour >= 4
```

条件成立後、最初のバーの close で全決済。

```text
exit_reason = Weekend
exit_price = close[current_bar]
```

---

# Daily Exit

日跨ぎ決済を使う場合は、指定時刻の close で決済する。

```text
hour == daily_exit_hour
exit_price = close[current_bar]
```

---

# Order Lifecycle

```text
NONE
↓
PENDING_ENTRY
↓
POSITION_OPEN
↓
EXITED
↓
NONE
```

---

# Signal Lifecycle

```text
NO_SIGNAL
↓
SIGNAL_ACTIVE
↓
ENTRY_TRIGGERED
↓
NO_SIGNAL
```

Signal は1つだけ保持する。

Signal Active 中に新しいSignalは作らない。

---

# Pending Entry Rule

Entry条件成立時、即座にポジションを持たない。

```text
Bar N:
entryCondition true
create pending market order

Bar N+1:
fill at open
```

---

# Position Rule

`pyramiding=0` のため、同時保有は1ポジションのみ。

Position Open 中は新規Signalも新規Entryも無視する。

---

# Trade Log Fields

全トレードで以下を保存する。

```text
entry_time
entry_bar_index
entry_price

exit_time
exit_bar_index
exit_price

side
profit
exit_reason

stop_price
limit_price

signal_time
signal_bar_index
signal_low
signal_high
```

---

# Validation Goal

TradingView の取引一覧と以下を一致させる。

```text
entry_time
entry_price
exit_time
exit_price
profit
trade_count
```

許容誤差

```text
price: 0.001
profit: 0.001
PF: ±0.01
WinRate: ±0.1%
```

---

# 今後の検証項目

TradingViewとの差が残る場合、以下を順番に確認する。

1. Entryが次バーOpenか
2. Entry条件成立バーが一致しているか
3. strategy.exitの有効化タイミング
4. SL/TP同時ヒット時の優先順位
5. close_allとexitの優先順位
6. Timezone
7. OHLCデータ差
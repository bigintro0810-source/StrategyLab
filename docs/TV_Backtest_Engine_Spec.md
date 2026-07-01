# TradingView Backtest Engine Specification
Version: 2.0

---

# 目的

TradingView Pine Script の strategy() を可能な限り忠実に再現する
Pythonバックテストエンジンを構築する。

本エンジンは Strategy Lab の全ストラテジーで共通利用する。

対象

- EMA戦略
- ICT
- FVG
- WEMOF
- Breakout
- 今後追加する全戦略

---

# 基本方針

戦略ロジックとバックテストエンジンは完全に分離する。

ストラテジーは

Signal

だけを返す。

エンジンは

注文
約定
SL
TP
決済
ログ

のみ担当する。

---

# State Machine

State 0

WAIT

↓

Signal発生

↓

State 1

SIGNAL_ACTIVE

SignalLow
SignalHigh
SignalBar

保持

↓

最大15本監視

↓

Close < SignalLow

↓

State2

ORDER_PENDING

注文発行

↓

次バー始値

↓

State3

POSITION_OPEN

↓

毎バー

SL判定

↓

TP判定

↓

Weekend判定

↓

Exit

↓

State0

WAIT

---

# Signal

Signal生成条件

- Session OK
- EMA条件
- RSI条件
- Body条件
- Breakout条件

Signal発生中は

新しいSignalは禁止

Pine

na(signalBar)

を再現する。

---

# Entry

TradingView

strategy.entry()

↓

次バー始値約定

エントリー価格

Open[next bar]

---

# Stop

SignalHigh固定

エントリー後

SignalHighは更新しない。

---

# TakeProfit

RR方式

Risk

=

StopPrice
-
EntryPrice

TP

=

EntryPrice
-
Risk
×RR

---

# Weekend Exit

Asia/Tokyo

土曜日

04:00

以降

最初のバー

Close決済

---

# Exit Priority

同一バー

SL

TP

両方ヒット

↓

TradingView仕様に合わせる

（後で検証）

---

# Trade Log

毎トレード保存

EntryTime

EntryPrice

ExitTime

ExitPrice

Stop

Target

Profit

ExitReason

SignalTime

SignalLow

SignalHigh

---

# Result

Trades

Wins

Losses

PF

NetProfit

GrossProfit

GrossLoss

MaxDD

WinRate

Expectancy

AverageTrade

Year Stability

Month Stability

WalkForwardScore

---

# Engine Rule

Engineは

ストラテジーを知らない。

Strategy

↓

Signal

↓

Engine

↓

Trade

---

# Optimizer

Optimizerは

Engine.run()

のみ呼ぶ。

---

# WalkForward

WalkForwardも

Engine.run()

のみ呼ぶ。

---

# MonteCarlo

TradeLogのみ使用

Engine変更不要

---

# Goal

TradingViewとの一致率

Entry

100%

Exit

100%

Trade Count

100%

PF

±0.01以内

WinRate

±0.1%

DD

±0.1%

これを達成したら

Strategy Lab標準エンジンとする。
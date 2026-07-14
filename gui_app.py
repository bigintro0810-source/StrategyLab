"""Streamlit GUI for Strategy Lab (V4.0 GUI化).

Wraps the existing main.py CLI via subprocess rather than importing its
run loop directly. main.py's optimization loop uses ProcessPoolExecutor,
which on Windows uses the "spawn" start method - worker processes
re-import __main__. If this GUI called that loop in-process, worker
processes would try to re-import/re-run the Streamlit app itself
(a known Streamlit+multiprocessing footgun on Windows: relaunching
workers as full Streamlit sessions, or hanging/erroring). Shelling out to
`python main.py ...` gives main.py its own clean __main__, sidesteps the
issue entirely, and means this GUI is a thin layer over the already-
tested CLI pipeline rather than a second implementation of it.

Run with: streamlit run gui_app.py
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.comparison_report import export_comparison_report
from engine.conditions import Condition, ConditionGroup
from engine.strategy_registry import get_strategy, list_strategies, update_strategy
from main import resolve_output_dir

st.set_page_config(page_title="Strategy Lab", layout="wide")
st.title("Strategy Lab")

with st.sidebar:
    st.warning(
        "**ご利用にあたって**\n\n"
        "本ソフトウェアは過去の値動きに基づく検証(バックテスト)ツールであり、"
        "投資助言・投資勧誘を目的としたものではありません。\n\n"
        "過去の成績は将来の成果を保証するものではありません。"
        "実際の取引に関する判断は、必ずご自身の責任において行ってください。\n\n"
        "本ソフトウェアの利用により生じたいかなる損害についても、"
        "開発者は責任を負いません。"
    )

TIMEFRAMES = ["1m", "5m", "10m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"]
SYMBOLS = ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "AUDUSD", "EURUSD", "GBPUSD", "XAUUSD", "XAGUSD"]

tab_run, tab_builder, tab_saved = st.tabs(["バックテスト実行", "条件ビルダー", "保存済み戦略"])

# 指標名 -> (表示名, 期間パラメータが必要か)。engine/conditions.py の
# INDICATOR_REGISTRY と対応させてあり、新しい指標を足す場合は両方に追加する。
BUILDER_INDICATORS = {
    "close": ("終値", False),
    "open": ("始値", False),
    "high": ("高値", False),
    "low": ("安値", False),
    "candle_body": ("実体(終値-始値、符号あり)", False),
    "ema": ("EMA", True),
    "rsi": ("RSI", True),
    "highest_high": ("直近高値(N本)", True),
    "lowest_low": ("直近安値(N本)", True),
    "highest_close": ("直近終値の最高値(N本)", True),
    "lowest_close": ("直近終値の最安値(N本)", True),
    "donchian_mid": ("ドンチアン中央値", True),
    "bollinger_upper": ("ボリンジャー上限", False),
    "bollinger_middle": ("ボリンジャー中央", False),
    "bollinger_lower": ("ボリンジャー下限", False),
    "macd_line": ("MACDライン", False),
    "macd_signal": ("MACDシグナル", False),
    "stochastic_k": ("ストキャスティクス%K", False),
    "stochastic_d": ("ストキャスティクス%D", False),
    "hour": ("時刻(JST)", False),
    "weekday": ("曜日(0=月〜6=日)", False),
}

BUILDER_OPERATORS = {
    ">": "より上 (>)",
    "<": "より下 (<)",
    ">=": "以上 (>=)",
    "<=": "以下 (<=)",
    "==": "一致 (==)",
    "crosses_above": "上抜け (crosses_above)",
    "crosses_below": "下抜け (crosses_below)",
}


with tab_run:
    with st.form("run_form"):
        col1, col2, col3 = st.columns(3)

        with col1:
            mode = st.selectbox("モード", ["dev", "full"])
            timeframe = st.selectbox("時間足", TIMEFRAMES, index=2)
            symbol = st.selectbox("通貨ペア", SYMBOLS)

        with col2:
            optimizer = st.selectbox("最適化方式", ["grid", "random", "genetic", "bayesian"])
            n_samples = st.number_input(
                "試行回数 (--optimizer random/bayesian時)", value=50, min_value=1, step=1
            )

        with col3:
            population = st.number_input(
                "世代あたり個体数 (--optimizer genetic時)", value=20, min_value=2, step=1
            )
            generations = st.number_input(
                "世代数 (--optimizer genetic時)", value=10, min_value=1, step=1
            )

        strategy_config_files = sorted(Path("strategy_configs").glob("*.json"))
        strategy_config_choice = st.selectbox(
            "ストラテジー設定ファイル (任意。指定すると--modeのグリッドより優先)",
            ["(使わない)"] + [str(path) for path in strategy_config_files],
        )

        save_as = st.text_input("保存名 (任意。指定するとsaved_strategies/に登録)")

        submitted = st.form_submit_button("実行")

    if submitted:
        cmd = [
            sys.executable, "main.py",
            "--mode", mode,
            "--timeframe", timeframe,
            "--symbol", symbol,
            "--optimizer", optimizer,
        ]

        if optimizer in ("random", "bayesian"):
            cmd += ["--n-samples", str(int(n_samples))]

        if optimizer == "genetic":
            cmd += ["--population", str(int(population)), "--generations", str(int(generations))]

        if strategy_config_choice != "(使わない)":
            cmd += ["--strategy-config", strategy_config_choice]

        if save_as:
            cmd += ["--save-as", save_as]

        with st.spinner(f"実行中: {' '.join(cmd)}"):
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        if process.returncode != 0:
            st.error("実行に失敗しました")
            st.code(process.stderr or process.stdout)
        else:
            st.success("完了しました")

            with st.expander("実行ログ"):
                st.code(process.stdout)

            output_dir = resolve_output_dir(symbol, timeframe)
            report_path = output_dir / "report.html"

            if report_path.exists():
                st.subheader("レポート")
                st.iframe(report_path.read_text(encoding="utf-8"), height=2600)

            ranking_path = output_dir / "ranking_total.csv"
            if ranking_path.exists():
                st.subheader("総合ランキング 上位20件")
                ranking_df = pd.read_csv(ranking_path).head(20)
                st.dataframe(ranking_df)
                st.download_button(
                    "ランキングCSVダウンロード",
                    ranking_path.read_bytes(),
                    file_name="ranking_total.csv",
                )

            pdf_report_path = output_dir / "report.pdf"
            if pdf_report_path.exists():
                st.download_button(
                    "PDFレポートダウンロード",
                    pdf_report_path.read_bytes(),
                    file_name="report.pdf",
                    mime="application/pdf",
                )


with tab_builder:
    st.subheader("条件ビルダー")
    st.caption(
        "エントリー条件をチェックボックスで組み立てて実行します。有効にした条件は全てAND(かつ)で結合されます。"
    )

    direction_label = st.radio("方向", ["Short(売り)", "Long(買い)"], horizontal=True)
    direction = "short" if direction_label.startswith("Short") else "long"

    condition_rows = []
    n_slots = 5

    for slot in range(n_slots):
        with st.container(border=True):
            cols = st.columns([0.6, 2, 1.2, 1.6, 1.4, 1.4])

            enabled = cols[0].checkbox("有効", key=f"cb_enabled_{slot}", value=(slot == 0))
            indicator = cols[1].selectbox(
                "指標",
                list(BUILDER_INDICATORS.keys()),
                format_func=lambda k: BUILDER_INDICATORS[k][0],
                key=f"cb_indicator_{slot}",
            )

            needs_period = BUILDER_INDICATORS[indicator][1]
            period = (
                cols[2].number_input("期間", value=14, min_value=1, step=1, key=f"cb_period_{slot}")
                if needs_period
                else None
            )

            operator = cols[3].selectbox(
                "演算子",
                list(BUILDER_OPERATORS.keys()),
                format_func=lambda k: BUILDER_OPERATORS[k],
                key=f"cb_operator_{slot}",
            )

            compare_mode = cols[4].radio(
                "比較先", ["固定値", "指標"], key=f"cb_comparemode_{slot}", horizontal=True
            )

            if compare_mode == "固定値":
                threshold = cols[5].number_input(
                    "しきい値", value=0.0, step=1.0, key=f"cb_threshold_{slot}"
                )
                value = threshold
                value_params = {}
            else:
                compare_indicator = cols[5].selectbox(
                    "比較先指標",
                    list(BUILDER_INDICATORS.keys()),
                    format_func=lambda k: BUILDER_INDICATORS[k][0],
                    key=f"cb_compareindicator_{slot}",
                )
                value = compare_indicator
                if BUILDER_INDICATORS[compare_indicator][1]:
                    compare_period = st.number_input(
                        "比較先の期間", value=14, min_value=1, step=1, key=f"cb_compareperiod_{slot}"
                    )
                    value_params = {"length": compare_period}
                else:
                    value_params = {}

            if enabled:
                params = {"length": period} if needs_period else {}
                condition_rows.append(
                    Condition(
                        indicator=indicator,
                        operator=operator,
                        value=value,
                        params=params,
                        value_params=value_params,
                    )
                )

    st.divider()
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        builder_mode = st.selectbox("モード", ["dev", "full"], key="builder_mode")
        builder_timeframe = st.selectbox("時間足", TIMEFRAMES, index=2, key="builder_timeframe")
        builder_symbol = st.selectbox("通貨ペア", SYMBOLS, key="builder_symbol")

    with col_b:
        builder_rr = st.number_input("Risk:Reward", value=1.2, step=0.1, key="builder_rr")
        builder_lookahead = st.number_input(
            "シグナル後の確認待ち(本数)", value=15, min_value=1, step=1, key="builder_lookahead"
        )
        builder_breakout_bars = st.number_input(
            "直近高値/安値の参照期間(本数)", value=30, min_value=1, step=1, key="builder_breakout_bars"
        )

    with col_c:
        builder_session_start = st.number_input(
            "セッション開始時刻(JST)", value=8, min_value=0, max_value=23, step=1, key="builder_session_start"
        )
        builder_session_end = st.number_input(
            "セッション終了時刻(JST)", value=3, min_value=0, max_value=23, step=1, key="builder_session_end"
        )
        builder_weekend_exit = st.checkbox("週末エグジット", value=True, key="builder_weekend_exit")

    builder_save_name = st.text_input(
        "この条件セットの保存名", value="", key="builder_save_name",
        help="strategy_configs/に保存され、実行時に--strategy-configとして使われます",
    )

    if st.button("条件ビルダーで実行", key="builder_run"):
        if not condition_rows:
            st.error("少なくとも1つは条件を有効にしてください")
        else:
            tree = (
                condition_rows[0].to_dict()
                if len(condition_rows) == 1
                else ConditionGroup(op="AND", children=condition_rows).to_dict()
            )

            strategy_params = {
                "ema_length": [200],
                "min_body_pips": [20.0],
                "max_body_pips": [0.0],
                "max_wick_pips": [0.0],
                "lookahead_bars": [int(builder_lookahead)],
                "breakout_bars": [int(builder_breakout_bars)],
                "ema_distance_pips": [50.0],
                "rsi_min": [70.0],
                "rr": [float(builder_rr)],
                "session_start": [int(builder_session_start)],
                "session_end": [int(builder_session_end)],
                "use_weekend_exit": [bool(builder_weekend_exit)],
                "weekend_exit_hour": [4],
                "use_daily_exit": [False],
                "daily_exit_hour": [4],
                "direction": [direction],
                "condition_tree": [tree],
            }

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            config_name = builder_save_name.strip() or f"builder_{timestamp}"
            config_path = Path("strategy_configs") / f"{config_name}.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps({"name": config_name, "params": strategy_params}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            cmd = [
                sys.executable, "main.py",
                "--mode", builder_mode,
                "--timeframe", builder_timeframe,
                "--symbol", builder_symbol,
                "--strategy-config", str(config_path),
            ]

            with st.spinner(f"実行中: {' '.join(cmd)}"):
                process = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
                )

            if process.returncode != 0:
                st.error("実行に失敗しました")
                st.code(process.stderr or process.stdout)
            else:
                st.success(f"完了しました(保存した条件: {config_path})")

                with st.expander("実行ログ"):
                    st.code(process.stdout)

                output_dir = resolve_output_dir(builder_symbol, builder_timeframe)
                ranking_path = output_dir / "ranking_total.csv"

                if ranking_path.exists():
                    st.subheader("ランキング")
                    st.dataframe(pd.read_csv(ranking_path).head(20))

                report_path = output_dir / "report.html"
                if report_path.exists():
                    st.subheader("レポート")
                    st.iframe(report_path.read_text(encoding="utf-8"), height=2600)


with tab_saved:
    st.subheader("保存済み戦略")

    entries = list_strategies()

    if not entries:
        st.info("保存済み戦略はまだありません。「バックテスト実行」タブで保存名を指定して実行してください。")
    else:
        table_rows = [
            {
                "id": entry["id"],
                "name": entry["name"],
                "favorite": "★" if entry["favorite"] else "",
                "mode": entry["mode"],
                "timeframe": entry["timeframe"],
                "tags": ", ".join(entry["tags"]),
                "memo": entry["memo"],
                **entry["metrics"],
            }
            for entry in entries
        ]
        st.dataframe(pd.DataFrame(table_rows))

        entry_ids = [entry["id"] for entry in entries]
        selected_id = st.selectbox("編集する戦略", entry_ids)
        selected_entry = get_strategy(selected_id)

        with st.form("edit_form"):
            new_name = st.text_input("名前", value=selected_entry["name"])
            new_tags = st.text_input("タグ(カンマ区切り)", value=", ".join(selected_entry["tags"]))
            new_memo = st.text_area("メモ", value=selected_entry["memo"])
            new_favorite = st.checkbox("お気に入り", value=selected_entry["favorite"])
            save_edit = st.form_submit_button("更新")

        if save_edit:
            tags_list = [tag.strip() for tag in new_tags.split(",") if tag.strip()]
            update_strategy(
                selected_id,
                name=new_name,
                tags=tags_list,
                memo=new_memo,
                favorite=new_favorite,
            )
            st.success("更新しました")
            st.rerun()

        st.divider()
        st.subheader("横断比較")

        compare_ids = st.multiselect("比較する戦略(複数選択)", entry_ids)

        if st.button("比較レポート生成") and compare_ids:
            comparison_path = export_comparison_report(compare_ids)
            st.iframe(Path(comparison_path).read_text(encoding="utf-8"), height=1200)

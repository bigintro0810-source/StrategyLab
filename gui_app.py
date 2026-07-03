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

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.comparison_report import export_comparison_report
from engine.strategy_registry import get_strategy, list_strategies, update_strategy
from main import resolve_output_dir

st.set_page_config(page_title="Strategy Lab", layout="wide")
st.title("Strategy Lab")

TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
SYMBOLS = ["USDJPY", "EURJPY", "GBPJPY"]

tab_run, tab_saved = st.tabs(["バックテスト実行", "保存済み戦略"])


with tab_run:
    with st.form("run_form"):
        col1, col2, col3 = st.columns(3)

        with col1:
            mode = st.selectbox("モード", ["dev", "full"])
            timeframe = st.selectbox("時間足", TIMEFRAMES, index=2)
            symbol = st.selectbox("通貨ペア", SYMBOLS)

        with col2:
            optimizer = st.selectbox("最適化方式", ["grid", "random", "genetic", "bayesian"])
            n_samples = st.number_input("random/bayesian: n_samples", value=50, min_value=1, step=1)

        with col3:
            population = st.number_input("genetic: population", value=20, min_value=2, step=1)
            generations = st.number_input("genetic: generations", value=10, min_value=1, step=1)

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

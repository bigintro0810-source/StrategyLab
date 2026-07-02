import argparse

from engine.comparison_report import export_comparison_report
from engine.strategy_registry import (
    add_tags,
    get_strategy,
    list_strategies,
    remove_tag,
    rename_strategy,
    set_memo,
    toggle_favorite,
)


def cmd_list(args: argparse.Namespace) -> None:
    entries = list_strategies(tag=args.tag, favorite_only=args.favorite)

    if not entries:
        print("保存された戦略はありません。")
        return

    for entry in entries:
        star = "★" if entry["favorite"] else " "
        tags = ",".join(entry["tags"]) if entry["tags"] else "-"
        metrics = entry["metrics"]
        net_profit = metrics.get("net_profit", "-")
        pf = metrics.get("profit_factor", "-")
        max_dd = metrics.get("max_dd", "-")

        print(
            f"{star} {entry['id']}  name={entry['name']}  "
            f"mode={entry['mode']} timeframe={entry['timeframe']}  "
            f"net_profit={net_profit} pf={pf} max_dd={max_dd}  "
            f"tags=[{tags}]"
        )
        if entry["memo"]:
            print(f"    memo: {entry['memo']}")


def cmd_tag(args: argparse.Namespace) -> None:
    entry = add_tags(args.id, args.tags)
    print(f"タグを追加しました: {entry['id']} -> {entry['tags']}")


def cmd_untag(args: argparse.Namespace) -> None:
    entry = remove_tag(args.id, args.tag)
    print(f"タグを削除しました: {entry['id']} -> {entry['tags']}")


def cmd_memo(args: argparse.Namespace) -> None:
    entry = set_memo(args.id, args.text)
    print(f"メモを更新しました: {entry['id']} -> {entry['memo']}")


def cmd_favorite(args: argparse.Namespace) -> None:
    entry = toggle_favorite(args.id)
    state = "お気に入りに追加" if entry["favorite"] else "お気に入りから解除"
    print(f"{state}しました: {entry['id']}")


def cmd_rename(args: argparse.Namespace) -> None:
    entry = rename_strategy(args.id, args.name)
    print(f"名前を変更しました: {entry['id']} -> {entry['name']}")


def cmd_show(args: argparse.Namespace) -> None:
    entry = get_strategy(args.id)
    for key, value in entry.items():
        print(f"{key}: {value}")


def cmd_compare(args: argparse.Namespace) -> None:
    report_path = export_comparison_report(args.ids)
    print(f"比較レポートを出力しました: {report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strategy Lab 保存済み戦略の管理")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="保存済み戦略の一覧表示")
    list_parser.add_argument("--tag", default=None, help="このタグを持つものだけ表示")
    list_parser.add_argument("--favorite", action="store_true", help="お気に入りのみ表示")
    list_parser.set_defaults(func=cmd_list)

    tag_parser = subparsers.add_parser("tag", help="タグを追加")
    tag_parser.add_argument("id")
    tag_parser.add_argument("tags", nargs="+")
    tag_parser.set_defaults(func=cmd_tag)

    untag_parser = subparsers.add_parser("untag", help="タグを削除")
    untag_parser.add_argument("id")
    untag_parser.add_argument("tag")
    untag_parser.set_defaults(func=cmd_untag)

    memo_parser = subparsers.add_parser("memo", help="メモを設定")
    memo_parser.add_argument("id")
    memo_parser.add_argument("text")
    memo_parser.set_defaults(func=cmd_memo)

    favorite_parser = subparsers.add_parser("favorite", help="お気に入りをトグル")
    favorite_parser.add_argument("id")
    favorite_parser.set_defaults(func=cmd_favorite)

    rename_parser = subparsers.add_parser("rename", help="名前を変更")
    rename_parser.add_argument("id")
    rename_parser.add_argument("name")
    rename_parser.set_defaults(func=cmd_rename)

    show_parser = subparsers.add_parser("show", help="詳細表示")
    show_parser.add_argument("id")
    show_parser.set_defaults(func=cmd_show)

    compare_parser = subparsers.add_parser("compare", help="複数戦略を横断比較したHTMLレポートを出力")
    compare_parser.add_argument("ids", nargs="+")
    compare_parser.set_defaults(func=cmd_compare)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

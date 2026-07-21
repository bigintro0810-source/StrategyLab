import type { ConditionNode, GroupNode, IndicatorInfo, TreeNode } from '../types'
import { isGroup } from '../types'
import { simplifyConditionTree } from '../conditionTreeUtils'
import { groupIndicatorsByGenre } from '../conditionGenres'
import ConditionRow, { defaultParamsFor } from './ConditionRow'

interface Props {
  node: GroupNode
  indicators: IndicatorInfo[]
  onChange: (next: GroupNode) => void
  onRemove?: () => void
  depth?: number
}

// 新しい条件のデフォルト指標は、生のindicators配列の先頭(たまたま「終値」
// など価格データ側になっていた)ではなく、一番上のジャンル「インジケーター」
// の先頭(EMAなど)にする(ユーザー報告:「インジケーター等ジャンルを選択する
// 際に最初価格データが選択されてる。一番上がインジケーターだから
// インジケーターを選択していてほしい」)。
function defaultCondition(indicators: IndicatorInfo[]): ConditionNode {
  const first = groupIndicatorsByGenre(indicators)[0]?.items[0] ?? indicators[0]
  return {
    indicator: first?.id ?? 'close',
    operator: '>',
    value: 0,
    params: defaultParamsFor(first),
    value_params: {},
  }
}

function defaultGroup(indicators: IndicatorInfo[]): GroupNode {
  return { op: 'AND', children: [defaultCondition(indicators)] }
}

export default function ConditionTreeEditor({ node, indicators, onChange, onRemove, depth = 0 }: Props) {
  const isNot = node.op === 'NOT'

  // グループの追加・削除を繰り返すと、子が1つだけの無意味な入れ子グループ
  // (AND(OR(AND(...)))など)が残ってしまうことがある(ユーザー報告:
  // 「グループをたくさん追加してから削除した際に画像のようにORの中に
  // ANDの中にANDが残ってしまう」)。ネストした各ConditionTreeEditorの
  // onChangeは最終的に全て一番外側(depth===0)のonChangeへ伝播するため、
  // そこだけで畳み込めば、ツリーのどの階層で行った操作でも自動的に整理
  // される。
  const emit = (next: GroupNode) => {
    onChange(depth === 0 ? (simplifyConditionTree(next) as GroupNode) : next)
  }

  const updateChild = (index: number, child: TreeNode) => {
    const children = node.children.slice()
    children[index] = child
    emit({ ...node, children })
  }

  const removeChild = (index: number) => {
    const children = node.children.slice()
    children.splice(index, 1)
    emit({ ...node, children })
  }

  const addCondition = () => {
    if (isNot && node.children.length >= 1) return
    emit({ ...node, children: [...node.children, defaultCondition(indicators)] })
  }

  const addGroup = () => {
    if (isNot && node.children.length >= 1) return
    emit({ ...node, children: [...node.children, defaultGroup(indicators)] })
  }

  return (
    <div
      // ANDのグループだけ枠で囲む(標準的な演算子の優先順位と同じ感覚 - ANDは
      // ORより強く結びつくので、その部分だけ括弧のように視覚的にまとめる)。
      // OR/NOTは枠なしにする(ユーザー要望:「AandBは囲ってAorBとAnotBは
      // 囲わないで」)。
      className={`space-y-2 rounded-lg p-2 ${node.op === 'AND' ? 'border border-white/10 bg-white/[0.02]' : ''}`}
      style={{ marginLeft: depth > 0 ? 12 : 0 }}
    >
      <div className="flex items-center gap-2">
        <select
          className="glass-input rounded-lg px-2 py-1 text-sm font-semibold"
          value={node.op}
          onChange={(e) => emit({ ...node, op: e.target.value as GroupNode['op'] })}
        >
          <option value="AND">AND</option>
          <option value="OR">OR</option>
          <option value="NOT">NOT</option>
        </select>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="rounded-lg border border-red-500/20 bg-red-500/10 px-2 py-1 text-xs text-red-300 hover:bg-red-500/20"
          >
            グループ削除
          </button>
        )}
      </div>

      {node.children.map((child, i) => {
        // A group (this one) can never be left with zero children - the
        // engine rejects an empty AND/OR/NOT with a raw Python traceback
        // (engine/conditions.py's ConditionGroup.__post_init__), so hide the
        // remove button on the last remaining child instead of letting the
        // user reach that state from the UI at all.
        const canRemove = node.children.length > 1
        return isGroup(child) ? (
          <ConditionTreeEditor
            key={i}
            node={child}
            indicators={indicators}
            depth={depth + 1}
            onChange={(next) => updateChild(i, next)}
            onRemove={canRemove ? () => removeChild(i) : undefined}
          />
        ) : (
          <ConditionRow
            key={i}
            node={child}
            indicators={indicators}
            onChange={(next) => updateChild(i, next)}
            onRemove={canRemove ? () => removeChild(i) : undefined}
          />
        )
      })}

      {(!isNot || node.children.length === 0) && (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={addCondition}
            className="rounded-lg border border-blue-400/20 bg-blue-400/10 px-2 py-1 text-xs text-blue-200 hover:bg-blue-400/20"
          >
            + 条件を追加
          </button>
          <button
            type="button"
            onClick={addGroup}
            className="rounded-lg border border-purple-400/20 bg-purple-400/10 px-2 py-1 text-xs text-purple-200 hover:bg-purple-400/20"
          >
            + グループを追加
          </button>
        </div>
      )}
    </div>
  )
}

import { useState } from 'react'

interface Props {
  defaultName: string
  isSaving: boolean
  error: string | null
  onSave: (name: string) => void
  onClose: () => void
}

// 合成タブの🔖/⭐から開く保存ダイアログ - 通常の行の🔖/⭐は既存の名称を
// そのまま使って即保存するが、合成結果は複数ストラテジーを束ねたもので
// 既定の単一名を持たないため、ここで名前を入力させてから保存する
// (ユーザー要望: 「しおりか星を押したらダイアログボックスが出現して。
// 名前を入力してから保存する」)。
export default function CompositeSaveDialog({ defaultName, isSaving, error, onSave, onClose }: Props) {
  const [name, setName] = useState(defaultName)

  const handleSave = () => {
    const trimmed = name.trim()
    if (trimmed && !isSaving) onSave(trimmed)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="glass-panel w-full max-w-sm rounded-2xl p-5">
        <h2 className="text-sm font-semibold text-gray-100">合成ストラテジーを保存</h2>
        <input
          type="text"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) handleSave()
            if (e.key === 'Escape') onClose()
          }}
          placeholder="名前を入力"
          className="glass-input mt-3 w-full rounded-lg px-2 py-1.5 text-sm"
        />
        {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="glass-input rounded-lg px-3 py-1.5 text-xs font-semibold text-gray-200 disabled:opacity-40"
          >
            キャンセル
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving || name.trim() === ''}
            className="glow-button rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
          >
            {isSaving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

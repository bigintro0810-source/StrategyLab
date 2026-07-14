import { useState } from 'react'
import { loadDefaultSettings, saveDefaultSettings, type DefaultSettings } from '../defaultSettings'

interface Props {
  subTab: string
}

export default function SettingsScreen({ subTab }: Props) {
  const [settings, setSettings] = useState<DefaultSettings>(() => loadDefaultSettings())
  const [saved, setSaved] = useState(false)

  const update = <K extends keyof DefaultSettings>(key: K, value: DefaultSettings[K]) => {
    setSettings((s) => ({ ...s, [key]: value }))
    setSaved(false)
  }

  const handleSave = () => {
    saveDefaultSettings(settings)
    setSaved(true)
    window.setTimeout(() => window.location.reload(), 600)
  }

  const SaveButton = (
    <>
      <button
        type="button"
        onClick={handleSave}
        className="glow-button mt-5 rounded-lg px-4 py-2 text-sm font-semibold text-white"
      >
        {saved ? '保存しました(再読み込み中…)' : '保存'}
      </button>
      <p className="mt-2 text-[11px] text-gray-500">
        保存すると、次に開くストラテジービルダーの初期値としてこの内容が使われます(ページを再読み込みします)。
      </p>
    </>
  )

  if (subTab === 'cost') {
    return (
      <div className="glass-panel max-w-xl rounded-2xl p-4">
        <div className="mb-3 text-sm font-semibold text-gray-200">既定の約定コスト</div>
        <div className="space-y-2 text-xs text-gray-300">
          <label className="flex items-center justify-between gap-2">
            <span>スプレッド(pips)</span>
            <input
              type="number"
              step={0.1}
              min={0}
              className="glass-input w-24 rounded-lg px-2 py-1"
              value={settings.spreadPips}
              onChange={(e) => update('spreadPips', Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span>スリッページ(pips)</span>
            <input
              type="number"
              step={0.1}
              min={0}
              className="glass-input w-24 rounded-lg px-2 py-1"
              value={settings.slippagePips}
              onChange={(e) => update('slippagePips', Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span>手数料(1取引あたり)</span>
            <input
              type="number"
              step={0.01}
              min={0}
              className="glass-input w-24 rounded-lg px-2 py-1"
              value={settings.commissionPerTrade}
              onChange={(e) => update('commissionPerTrade', Number(e.target.value))}
            />
          </label>
        </div>
        {SaveButton}
      </div>
    )
  }

  if (subTab === 'execution') {
    return (
      <div className="glass-panel max-w-xl rounded-2xl p-4">
        <div className="mb-3 text-sm font-semibold text-gray-200">既定の口座設定</div>
        <div className="space-y-2 text-xs text-gray-300">
          <label className="flex items-center justify-between gap-2">
            <span>初期資金</span>
            <input
              type="number"
              step={10000}
              min={0}
              className="glass-input w-32 rounded-lg px-2 py-1"
              value={settings.initialCapital}
              onChange={(e) => update('initialCapital', Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span>口座通貨</span>
            <select
              className="glass-input w-24 rounded-lg px-2 py-1"
              value={settings.accountCurrency}
              onChange={(e) => update('accountCurrency', e.target.value as 'JPY' | 'USD')}
            >
              <option value="JPY">JPY</option>
              <option value="USD">USD</option>
            </select>
          </label>
          <label className="flex items-center justify-between gap-2">
            <span>リスク%(1取引あたり)</span>
            <input
              type="number"
              step={0.1}
              min={0.01}
              className="glass-input w-24 rounded-lg px-2 py-1"
              value={settings.riskPercent}
              onChange={(e) => update('riskPercent', Number(e.target.value))}
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span>為替換算レート(通貨ペア⇔口座通貨)</span>
            <input
              type="number"
              step={0.01}
              min={0.01}
              className="glass-input w-24 rounded-lg px-2 py-1"
              value={settings.conversionRate}
              onChange={(e) => update('conversionRate', Number(e.target.value))}
            />
          </label>
        </div>
        <div className="mt-2 text-[11px] text-gray-500">
          ※為替換算レートはバックテスト全期間で固定の概算値です(日々の実勢レートではありません)
        </div>
        {SaveButton}
      </div>
    )
  }

  if (subTab === 'timezone') {
    return (
      <div className="glass-panel max-w-xl rounded-2xl p-4">
        <div className="mb-3 text-sm font-semibold text-gray-200">タイムゾーン</div>
        <p className="mb-3 text-xs text-gray-400">
          チャート・取引履歴に表示する時刻の基準です。データ自体は取り込み時にJST(日本時間)へ正規化されて保存されているため、
          ここでの変更は表示上の見え方だけに影響し、バックテストの計算結果は変わりません。
        </p>
        <label className="flex items-center justify-between gap-2 text-xs text-gray-300">
          <span>表示タイムゾーン</span>
          <select
            className="glass-input w-40 rounded-lg px-2 py-1"
            value={settings.displayTimezone}
            onChange={(e) => update('displayTimezone', e.target.value as DefaultSettings['displayTimezone'])}
          >
            <option value="JST">JST(日本時間・保存形式のまま)</option>
            <option value="UTC">UTC</option>
            <option value="broker">ブローカーサーバー時間(EET)</option>
          </select>
        </label>
        {SaveButton}
      </div>
    )
  }

  return (
    <div className="glass-panel max-w-xl rounded-2xl p-4">
      <div className="mb-3 text-sm font-semibold text-gray-200">一般設定</div>
      <p className="text-xs text-gray-400">現在、全般設定の項目はありません。約定コスト・口座設定・タイムゾーンは各タブから設定してください。</p>
    </div>
  )
}

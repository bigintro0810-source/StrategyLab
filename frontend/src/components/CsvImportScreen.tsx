import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { browseFolder, fetchBacktestStatus, importCsv } from '../api'

// import_broker_csv.pyのTIMEFRAME_LABELSと同じ対応表 - 右側の説明パネルで
// 「時間足ごとに実際に必要なファイル名」を具体的に示すため(ユーザー要望:
// 「その説明をインポート画面に書いて」)。
// ユーザーが貼ったCSV(Excelで開いた見た目)のスクリーンショット例の
// 6行目まで(見出し+データ5行、7行目以降は不要とのこと) - 実際の画像
// ファイルではなく、同じ内容のHTMLテーブルとして再現している(アプリの
// ダークテーマにも馴染ませるため)。
const CSV_EXAMPLE_ROWS: [string, string, string, string, string, string][] = [
  ['2003.05.05 00:00:00', '118.94', '119.016', '118.926', '118.951', '3468.2'],
  ['2003.05.05 00:15:00', '118.947', '118.975', '118.933', '118.949', '3108.9'],
  ['2003.05.05 00:30:00', '118.954', '118.975', '118.893', '118.959', '3083.3'],
  ['2003.05.05 00:45:00', '118.966', '118.991', '118.923', '118.976', '2914.6'],
  ['2003.05.05 01:00:00', '118.993', '119', '118.967', '118.985', '3088.8'],
]

const TIMEFRAME_LABELS: Record<string, string> = {
  '1m': '1 Min',
  '5m': '5 Mins',
  '10m': '10 Mins',
  '15m': '15 Mins',
  '30m': '30 Mins',
  '1h': 'Hourly',
  '4h': '4 Hours',
  '1d': 'Daily',
  '1w': 'Weekly',
  '1mo': 'Monthly',
}

interface Props {
  // ディスク上に実際にインポート済みの通貨一覧(App.tsx::symbolsQuery
  // 参照) - チェックボックスの選択肢として出す。新しい通貨ペアはここに
  // 無くても下の入力欄から自由に追加できる(ユーザー要望: 「俺以外の
  // ユーザーがどの通貨でも任意でインポートできるようにしたい」)。
  symbols: string[]
  timeframes: string[]
}

export default function CsvImportScreen({ symbols, timeframes }: Props) {
  const queryClient = useQueryClient()
  const [sourceRoot, setSourceRoot] = useState('')
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [newSymbolInput, setNewSymbolInput] = useState('')
  const [selectedTimeframes, setSelectedTimeframes] = useState<string[]>(['15m'])
  // 取り込み元CSVのタイムスタンプが実際にどのタイムゾーンかは提供元次第
  // (必ずEETとは限らない) - ユーザー要望:「もしもとからJSTのデータでも
  // 勝手にEETって認識して変換しちゃうの?」への対応(api.ts::importCsv/
  // api_server.py::CsvImportRequest.source_timezone参照)。
  const [sourceTimezone, setSourceTimezone] = useState<'EET' | 'JST' | 'UTC'>('EET')
  // ユーザー要望:「23年分は残したい」- trueの時は出力先を丸ごと置き換えず、
  // 既存データは保持したまま無い日時の行だけを追加する(import_broker_csv.py
  // ::merge_into_existing参照)。
  const [merge, setMerge] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)

  const statusQuery = useQuery({
    queryKey: ['csv-import-status', jobId],
    queryFn: () => fetchBacktestStatus(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'done' || status === 'error' ? false : 1500
    },
    refetchIntervalInBackground: true,
  })
  const status = statusQuery.data?.status
  // import_broker_csv.pyは、CSVが見つからない時間足だけスキップして残りを
  // 続行する(ユーザー要望:「見つからなかったものは飛ばしてほかのやつは
  // 成功にできる?」)。標準出力は末尾2000文字しか届かない
  // (api_server.py::get_backtest_status)ため、処理途中で出す1件ずつの行
  // ではなく、最後にまとめて出す要約(常に末尾に来る)を拾う - "  * "が
  // 実際に変換できた分(ユーザー要望:「どこまで上書きしたかはわかる?」)、
  // "  - "が見つからずスキップした分。
  const stdoutTail = statusQuery.data?.stdout_tail ?? ''
  const completedLines = stdoutTail
    .split('\n')
    .filter((line) => line.startsWith('  * '))
    .map((line) => line.slice('  * '.length))
  const skippedLines = stdoutTail
    .split('\n')
    .filter((line) => line.startsWith('  - '))
    .map((line) => line.slice('  - '.length))

  // インポート完了時に通貨一覧・通貨ごとの時間足一覧(App.tsx::symbolsQuery
  // /symbolTimeframesQuery)を再取得させ、新しく取り込んだ通貨/時間足を
  // ピッカー類にすぐ反映する - refがないとstatusが'done'のままの再レンダ
  // リングのたびに何度もinvalidateしてしまう。
  const invalidatedForJob = useRef<string | null>(null)
  useEffect(() => {
    if (status === 'done' && jobId !== null && invalidatedForJob.current !== jobId) {
      invalidatedForJob.current = jobId
      queryClient.invalidateQueries({ queryKey: ['data-symbols'] })
      queryClient.invalidateQueries({ queryKey: ['data-symbol-timeframes'] })
    }
  }, [status, jobId, queryClient])

  const addNewSymbol = () => {
    const value = newSymbolInput.trim().toUpperCase()
    if (!value) return
    if (!selectedSymbols.includes(value)) setSelectedSymbols([...selectedSymbols, value])
    setNewSymbolInput('')
  }

  const runMutation = useMutation({
    mutationFn: (skipExisting: boolean) =>
      importCsv(sourceRoot, selectedSymbols, selectedTimeframes, skipExisting, sourceTimezone, merge),
    onSuccess: (data) => setJobId(data.job_id),
  })

  // サーバー側(このPC自身)でネイティブのフォルダ選択ダイアログを開く -
  // ブラウザ標準のfile inputは絶対パスを返さないため使えない
  // (api_server.py::browse_folder参照)。
  const browseMutation = useMutation({
    mutationFn: () => browseFolder(),
    onSuccess: (path) => {
      if (path) setSourceRoot(path)
    },
  })

  const toggle = (list: string[], set: (v: string[]) => void, value: string) => {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])
  }

  const canRun = sourceRoot.trim() !== '' && selectedSymbols.length > 0 && selectedTimeframes.length > 0 && confirmed

  return (
    <div className="flex flex-wrap items-start gap-4">
    <div className="glass-panel max-w-2xl flex-1 rounded-2xl p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">CSVインポート</div>
      <p className="mb-3 text-xs text-gray-400">
        ブローカー提供のCSVを、通貨ペアごとのフォルダ(<code>{'{フォルダ}'}\\{'{通貨ペア}'}_Data\\</code>)から
        JST変換して取り込みます。既存の同名データファイルは既定では丸ごと上書きされます(元に戻せません)。
        下の「マージモード」を有効にすると、既存データを消さずに無い期間だけ追加できます。
      </p>

      <label className="mb-3 block text-xs text-gray-300">
        <span className="mb-1 block text-gray-400">取り込み元フォルダ</span>
        <div className="flex gap-1.5">
          <input
            type="text"
            placeholder="例: C:\Users\...\FX_Data"
            className="glass-input w-full rounded-lg px-2 py-1.5"
            value={sourceRoot}
            onChange={(e) => setSourceRoot(e.target.value)}
          />
          <button
            type="button"
            onClick={() => browseMutation.mutate()}
            disabled={browseMutation.isPending}
            className="glass-input flex-none rounded-lg px-3 py-1.5 font-semibold text-gray-200 hover:bg-white/10 disabled:opacity-40"
          >
            {browseMutation.isPending ? '選択中…' : '参照...'}
          </button>
        </div>
        {browseMutation.isError && (
          <p className="mt-1 text-[11px] text-red-400">フォルダ選択ダイアログを開けませんでした</p>
        )}
      </label>

      <div className="mb-3">
        <div className="mb-1 text-xs text-gray-400">対象通貨ペア</div>
        <div className="flex flex-wrap gap-2 text-xs">
          {symbols.map((s) => (
            <label key={s} className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1">
              <input
                type="checkbox"
                checked={selectedSymbols.includes(s)}
                onChange={() => toggle(selectedSymbols, setSelectedSymbols, s)}
              />
              {s}
            </label>
          ))}
          {selectedSymbols
            .filter((s) => !symbols.includes(s))
            .map((s) => (
              <span
                key={s}
                className="flex items-center gap-1 rounded-lg border border-blue-400/30 bg-blue-500/10 px-2 py-1 text-blue-200"
              >
                {s}
                <button
                  type="button"
                  onClick={() => toggle(selectedSymbols, setSelectedSymbols, s)}
                  className="text-blue-300 hover:text-blue-100"
                >
                  ×
                </button>
              </span>
            ))}
        </div>
        <div className="mt-1.5 flex gap-1.5">
          <input
            type="text"
            placeholder="まだ無い通貨ペアを追加(例: USDCAD)"
            className="glass-input w-52 rounded-lg px-2 py-1 text-xs"
            value={newSymbolInput}
            onChange={(e) => setNewSymbolInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                e.preventDefault()
                addNewSymbol()
              }
            }}
          />
          <button
            type="button"
            onClick={addNewSymbol}
            className="glass-input flex-none rounded-lg px-2 py-1 text-xs font-semibold text-gray-200 hover:bg-white/10"
          >
            + 追加
          </button>
        </div>
      </div>

      <div className="mb-3">
        <div className="mb-1 text-xs text-gray-400">対象時間足</div>
        <div className="flex flex-wrap gap-2 text-xs">
          {timeframes.map((tf) => (
            <label key={tf} className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1">
              <input
                type="checkbox"
                checked={selectedTimeframes.includes(tf)}
                onChange={() => toggle(selectedTimeframes, setSelectedTimeframes, tf)}
              />
              {tf}
            </label>
          ))}
        </div>
      </div>

      <label className="mb-3 block text-xs text-gray-300">
        <span className="mb-1 block text-gray-400">取り込み元のタイムゾーン</span>
        <select
          className="glass-input rounded-lg px-2 py-1.5"
          value={sourceTimezone}
          onChange={(e) => setSourceTimezone(e.target.value as 'EET' | 'JST' | 'UTC')}
        >
          <option value="EET">EET(東欧時間、ブローカーのCSVで一般的)</option>
          <option value="JST">JST(日本時間)</option>
          <option value="UTC">UTC(協定世界時)</option>
        </select>
        <p className="mt-1 text-[11px] text-gray-500">
          CSVの日時をこのタイムゾーンとして読み込みます。JST以外を選んだ場合は取り込み時に自動的にJSTへ変換されます(JSTを選んだ場合は変換なしでそのまま取り込まれます)。
        </p>
      </label>

      <label className="mb-3 flex items-center gap-1.5 text-xs text-gray-300">
        <input type="checkbox" checked={merge} onChange={(e) => setMerge(e.target.checked)} />
        マージモード(既存データは消さず、無い日時の行だけ追加する)
      </label>
      {merge && (
        <p className="-mt-2 mb-3 text-[11px] text-gray-500">
          重複する日時は既存データ側の値を優先します(取り込むCSV側の値では上書きしません)。
        </p>
      )}

      <label className="mb-3 flex items-center gap-1.5 text-xs text-amber-300">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        {merge
          ? '既存のデータファイルに新しいデータを追加することを確認しました'
          : '既存のデータファイルを上書きすることを確認しました'}
      </label>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => runMutation.mutate(false)}
          disabled={!canRun || runMutation.isPending || (status && status !== 'done' && status !== 'error')}
          className="glow-button rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
        >
          インポート実行
        </button>
        {status === 'error' && (
          <button
            type="button"
            onClick={() => runMutation.mutate(true)}
            disabled={runMutation.isPending}
            title="既に変換できている分はやり直さず、残りだけ処理します"
            className="glass-input rounded-lg px-4 py-2 text-sm font-semibold text-gray-200 hover:bg-white/10 disabled:opacity-40"
          >
            続きから再開
          </button>
        )}
      </div>

      {status && status !== 'done' && status !== 'error' && (
        <p className="mt-3 text-xs text-gray-400">実行中…(データ量によっては数分かかります)</p>
      )}
      {status === 'done' && (
        <div className="mt-3">
          <p className="text-xs text-emerald-400">完了しました。{completedLines.length > 0 && `(${completedLines.length}件変換)`}</p>
          {skippedLines.length > 0 && (
            <div className="mt-1 rounded-lg border border-amber-400/20 bg-amber-500/10 p-2 text-[11px] text-amber-300">
              <div className="mb-0.5 font-semibold">ファイルが見つからずスキップしたもの({skippedLines.length}件)</div>
              {skippedLines.map((line) => (
                <div key={line}>・{line}</div>
              ))}
            </div>
          )}
        </div>
      )}
      {status === 'error' && (
        <div className="mt-3">
          <p className="whitespace-pre-wrap text-xs text-red-400">{statusQuery.data?.error_summary}</p>
          {/* ユーザー要望:「どこまで上書きしたかはわかる?」- エラーで
              止まっても、その時点までに実際に変換できた分は既にdata/raw
              側へ反映されている(import_broker_csv.pyのfinally節参照)。 */}
          {completedLines.length > 0 && (
            <div className="mt-1 rounded-lg border border-emerald-400/20 bg-emerald-500/10 p-2 text-[11px] text-emerald-300">
              <div className="mb-0.5 font-semibold">ここまで変換できたもの({completedLines.length}件、既に反映済み)</div>
              {completedLines.map((line) => (
                <div key={line}>・{line}</div>
              ))}
            </div>
          )}
          {skippedLines.length > 0 && (
            <div className="mt-1 rounded-lg border border-amber-400/20 bg-amber-500/10 p-2 text-[11px] text-amber-300">
              <div className="mb-0.5 font-semibold">ファイルが見つからずスキップしたもの({skippedLines.length}件)</div>
              {skippedLines.map((line) => (
                <div key={line}>・{line}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>

    <div className="glass-panel w-[58rem] flex-none rounded-2xl p-4 text-xs text-gray-300">
      <div className="mb-2 text-sm font-semibold text-gray-200">フォルダ・ファイル名の形式</div>

      <div className="grid grid-cols-[2fr_3fr] gap-4">
        <div>
          <div className="mb-1 text-gray-400">① フォルダ構成</div>
          <pre className="mb-3 whitespace-pre-wrap rounded-lg border border-white/10 bg-white/[0.02] p-2 font-mono text-[11px] text-gray-300">
{`FX_Data\\
└ USDJPY_Data\\
    ├ USDJPY_15 Mins_Bid_....csv
    ├ USDJPY_Hourly_Bid_....csv
    └ ...(時間足ごとに1つ)`}
          </pre>
          <p className="mb-3 text-gray-400">
            「参照...」で選ぶのは<code>USDJPY_Data</code>ではなく、一つ上の<code>FX_Data</code>フォルダ自体です。
          </p>

          <div className="mb-1 text-gray-400">② 時間足ごとのファイル名</div>
          <p className="mb-1.5 text-gray-400">
            <code>{'{通貨ペア}'}_</code>の後ろが下の表と一致していれば、末尾(<code>_Bid_〜.csv</code>の〜の部分)は何でも構いません。
          </p>
          <table className="w-full text-left text-[11px]">
            <tbody>
              {Object.entries(TIMEFRAME_LABELS).map(([tf, label]) => (
                <tr key={tf} className="border-b border-white/5">
                  <td className="py-0.5 pr-2 text-gray-400">{tf}</td>
                  <td className="py-0.5 font-mono text-gray-300">
                    USDJPY_{label}_Bid_〜.csv
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <div className="mb-1 text-gray-400">③ ファイル内の形式(1行目・日時)</div>
          <p className="mb-1.5 text-gray-400">
            1行目(見出し)は下記の列名が必要です。1列目は<code>Time</code>で始まる名前なら何でも構いませんが、
            <code>Open</code>/<code>High</code>/<code>Low</code>/<code>Close</code>は完全に一致している必要があります。
            <code>Volume</code>列は無くても構いません(無い場合は0として扱われ、出来高系インジケーターを使わない限り結果に影響しません)。
          </p>
          <div className="mb-1.5 overflow-x-auto rounded-lg border border-gray-300 bg-white">
            <table className="w-full border-collapse text-left text-[11px] text-gray-900">
              <thead>
                <tr className="bg-gray-100">
                  <th className="whitespace-nowrap border border-gray-300 px-1.5 py-0.5 font-semibold">Time (EET)</th>
                  <th className="whitespace-nowrap border border-gray-300 px-1.5 py-0.5 font-semibold">Open</th>
                  <th className="whitespace-nowrap border border-gray-300 px-1.5 py-0.5 font-semibold">High</th>
                  <th className="whitespace-nowrap border border-gray-300 px-1.5 py-0.5 font-semibold">Low</th>
                  <th className="whitespace-nowrap border border-gray-300 px-1.5 py-0.5 font-semibold">Close</th>
                  <th className="whitespace-nowrap border border-gray-300 px-1.5 py-0.5 font-semibold">Volume</th>
                </tr>
              </thead>
              <tbody>
                {CSV_EXAMPLE_ROWS.map((row) => (
                  <tr key={row[0]}>
                    {row.map((cell, i) => (
                      <td key={i} className="whitespace-nowrap border border-gray-300 px-1.5 py-0.5">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-gray-400">
            日時は<code>年.月.日 時:分:秒</code>(ピリオド区切り)の形式である必要があります。左側の「取り込み元のタイムゾーン」欄で選んだタイムゾーン(既定はブローカーのCSVで一般的なEET/東欧時間)として読み込まれ、JST以外を選んだ場合は取り込み時に自動的に日本時間へ変換されます。
          </p>

          <div className="mt-4 border-t border-white/10 pt-3">
            <div className="mb-1 text-gray-400">④ 注意点</div>
            <ul className="list-disc space-y-1 pl-4 text-gray-400">
              <li>チェックした時間足のうち、CSVが見つからないものはスキップされ、見つかったものだけ変換されます。全部見つからなかった時だけエラーになります。</li>
              <li>
                エラーで停止しても、それより前に処理した分は既に反映されています。「完了しました」/エラー表示の下に、どこまで成功したかが一覧で出ます。「続きから再開」ボタンを押すと、既に変換できている分はやり直さず残りだけ処理します。
              </li>
              <li>上書きは元に戻せません(バックアップは取られません)。</li>
              <li>1分足など細かい時間足はファイルが巨大で、変換に時間がかかります。</li>
              <li>インポート中にサーバー(バックエンドのコンソール)を閉じると、処理が途中で中断されます。</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
    </div>
  )
}

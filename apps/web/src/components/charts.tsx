// Small SVG charts for the Evaluation page. Colors come from validated tokens
// (series 1-3), marks are thin, every chart has a hover/focus tooltip and a table twin.
import { useId, useState, type ReactNode } from 'react'
import { cn, formatPct } from '../lib/format'

export const SERIES = ['var(--t-series-1)', 'var(--t-series-2)', 'var(--t-series-3)']

export function ChartFrame({ title, legend, table, children, caption }: { title: string; legend?: ReactNode; table: ReactNode; children: ReactNode; caption?: string }) {
  const [asTable, setAsTable] = useState(false)
  const id = useId()
  return (
    <figure className="rounded-xl bg-surface p-4 ring-1 ring-line" aria-labelledby={id}>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <figcaption id={id} className="text-sm font-semibold text-ink">{title}</figcaption>
        <button type="button" onClick={() => setAsTable((v) => !v)} className="text-xs text-brand underline underline-offset-2">
          {asTable ? 'Tampilkan grafik' : 'Tampilkan tabel'}
        </button>
      </div>
      {legend && !asTable && <div className="mb-2 flex flex-wrap gap-3 text-xs text-ink-2">{legend}</div>}
      {asTable ? <div className="overflow-x-auto">{table}</div> : children}
      {caption && <p className="mt-2 text-xs text-ink-2">{caption}</p>}
    </figure>
  )
}

export function LegendKey({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="14" height="4" aria-hidden><line x1="0" y1="2" x2="14" y2="2" stroke={color} strokeWidth="2" strokeLinecap="round" /></svg>
      {label}
    </span>
  )
}

const W = 560
const H = 300
const M = { l: 44, r: 16, t: 12, b: 36 }
const px = (v: number) => M.l + v * (W - M.l - M.r)
const py = (v: number, lo = 0, hi = 1) => H - M.b - ((v - lo) / (hi - lo)) * (H - M.t - M.b)

function Axes({ yLo = 0, yHi = 1, xLabel, yLabel }: { yLo?: number; yHi?: number; xLabel: string; yLabel: string }) {
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  const yTicks = ticks.map((t) => yLo + t * (yHi - yLo))
  return (
    <g className="text-[10px]" fill="var(--t-muted)">
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={M.l} x2={W - M.r} y1={py(t, yLo, yHi)} y2={py(t, yLo, yHi)} stroke="var(--t-line)" strokeWidth="1" />
          <text x={M.l - 6} y={py(t, yLo, yHi) + 3} textAnchor="end" className="num">{Math.round(t * 100)}%</text>
        </g>
      ))}
      {ticks.map((t) => (
        <text key={t} x={px(t)} y={H - M.b + 14} textAnchor="middle" className="num">{Math.round(t * 100)}%</text>
      ))}
      <line x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} stroke="var(--t-line-strong)" />
      <text x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle" fill="var(--t-ink-2)">{xLabel}</text>
      <text x={12} y={(M.t + H - M.b) / 2} textAnchor="middle" fill="var(--t-ink-2)" transform={`rotate(-90 12 ${(M.t + H - M.b) / 2})`}>{yLabel}</text>
    </g>
  )
}

export interface Bin { lo: number; hi: number; n: number; confidence: number | null; accuracy: number | null }

/** Reliability diagram: mean confidence vs observed accuracy per bin, one line per method. */
export function ReliabilityChart({ series }: { series: { name: string; ece: number; bins: Bin[] }[] }) {
  const [tip, setTip] = useState<{ name: string; b: Bin } | null>(null)
  const shown = series.slice(0, 3)
  return (
    <ChartFrame
      title="Kurva keandalan (kalibrasi keyakinan field)"
      caption="Garis diagonal = kalibrasi sempurna. Titik di bawah diagonal berarti sistem terlalu yakin."
      legend={shown.map((s, i) => <LegendKey key={s.name} color={SERIES[i]} label={`${s.name} · ECE ${s.ece.toFixed(3)}`} />)}
      table={
        <table className="w-full text-xs">
          <thead><tr className="text-left text-ink-2"><th className="py-1">Metode</th><th>Bin</th><th className="text-right">n</th><th className="text-right">Keyakinan</th><th className="text-right">Akurasi</th></tr></thead>
          <tbody className="num">
            {shown.flatMap((s) => s.bins.filter((b) => b.n).map((b) => (
              <tr key={`${s.name}-${b.lo}`} className="border-t border-line"><td className="py-1">{s.name}</td><td>{b.lo.toFixed(1)}–{b.hi.toFixed(1)}</td><td className="text-right">{b.n}</td><td className="text-right">{formatPct(b.confidence)}</td><td className="text-right">{formatPct(b.accuracy)}</td></tr>
            )))}
          </tbody>
        </table>
      }
    >
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Kurva keandalan">
          <Axes xLabel="Keyakinan rata-rata per bin" yLabel="Akurasi teramati" />
          <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} stroke="var(--t-line-strong)" strokeWidth="1" />
          {shown.map((s, i) => {
            const pts = s.bins.filter((b) => b.n && b.confidence != null && b.accuracy != null)
            return (
              <g key={s.name}>
                <polyline fill="none" stroke={SERIES[i]} strokeWidth="2" strokeLinejoin="round" points={pts.map((b) => `${px(b.confidence!)},${py(b.accuracy!)}`).join(' ')} />
                {pts.map((b) => (
                  <g key={b.lo} tabIndex={0} onMouseEnter={() => setTip({ name: s.name, b })} onMouseLeave={() => setTip(null)}
                    onFocus={() => setTip({ name: s.name, b })} onBlur={() => setTip(null)}>
                    <circle cx={px(b.confidence!)} cy={py(b.accuracy!)} r={12} fill="transparent" />
                    <circle cx={px(b.confidence!)} cy={py(b.accuracy!)} r={4.5} fill={SERIES[i]} stroke="var(--t-surface)" strokeWidth="2" />
                  </g>
                ))}
              </g>
            )
          })}
        </svg>
        {tip && (
          <div className="pointer-events-none absolute left-14 top-2 rounded-md bg-surface px-2.5 py-1.5 text-xs shadow-lg ring-1 ring-line-strong" role="status">
            <p className="font-semibold text-ink">{tip.name}</p>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Keyakinan</span><strong className="num">{formatPct(tip.b.confidence)}</strong></div>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Akurasi</span><strong className="num">{formatPct(tip.b.accuracy)}</strong></div>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Jumlah field</span><strong className="num">{tip.b.n}</strong></div>
          </div>
        )}
      </div>
    </ChartFrame>
  )
}

/** Coverage vs accuracy: how many documents can be auto-approved at each accuracy. */
export function CoverageChart({ points, target, chosen }: { points: { threshold: number; coverage: number; accuracy: number }[]; target: number; chosen?: { coverage: number; accuracy: number } | null }) {
  const [hover, setHover] = useState<number | null>(null)
  const yLo = Math.max(0, Math.floor(Math.min(...points.map((p) => p.accuracy), target) * 20) / 20 - 0.05)
  const sorted = [...points].sort((a, b) => a.coverage - b.coverage)
  const h = hover != null ? sorted[hover] : null
  return (
    <ChartFrame
      title="Coverage vs akurasi (dokumen lolos otomatis)"
      caption={`Garis horizontal = target akurasi ${formatPct(target)}. Titik bulat = ambang yang dipilih pada data validasi, diterapkan ke data uji.`}
      table={
        <table className="w-full text-xs">
          <thead><tr className="text-left text-ink-2"><th className="py-1">Ambang keyakinan</th><th className="text-right">Coverage</th><th className="text-right">Akurasi</th></tr></thead>
          <tbody className="num">{sorted.map((p) => <tr key={p.threshold} className="border-t border-line"><td className="py-1">{p.threshold.toFixed(3)}</td><td className="text-right">{formatPct(p.coverage)}</td><td className="text-right">{formatPct(p.accuracy)}</td></tr>)}</tbody>
        </table>
      }
    >
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Kurva coverage terhadap akurasi"
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
            const x = ((e.clientX - r.left) / r.width) * W
            const cov = (x - M.l) / (W - M.l - M.r)
            let best = 0
            sorted.forEach((p, i) => { if (Math.abs(p.coverage - cov) < Math.abs(sorted[best].coverage - cov)) best = i })
            setHover(best)
          }}>
          <Axes yLo={yLo} xLabel="Coverage (porsi dokumen yang lolos otomatis)" yLabel="Akurasi dokumen lolos" />
          <line x1={px(0)} x2={px(1)} y1={py(target, yLo)} y2={py(target, yLo)} stroke="var(--t-good)" strokeWidth="1.5" />
          <text x={px(1) - 4} y={py(target, yLo) - 5} textAnchor="end" fontSize="10" fill="var(--t-good)">target {formatPct(target)}</text>
          <polyline fill="none" stroke={SERIES[0]} strokeWidth="2" strokeLinejoin="round" points={sorted.map((p) => `${px(p.coverage)},${py(p.accuracy, yLo)}`).join(' ')} />
          {chosen && <circle cx={px(chosen.coverage)} cy={py(chosen.accuracy, yLo)} r={6} fill={SERIES[0]} stroke="var(--t-surface)" strokeWidth="2" />}
          {h && (
            <g>
              <line x1={px(h.coverage)} x2={px(h.coverage)} y1={M.t} y2={H - M.b} stroke="var(--t-line-strong)" />
              <circle cx={px(h.coverage)} cy={py(h.accuracy, yLo)} r={4.5} fill={SERIES[0]} stroke="var(--t-surface)" strokeWidth="2" />
            </g>
          )}
        </svg>
        {h && (
          <div className="pointer-events-none absolute top-2 rounded-md bg-surface px-2.5 py-1.5 text-xs shadow-lg ring-1 ring-line-strong" style={{ left: `min(calc(${(px(h.coverage) / W) * 100}% + 8px), calc(100% - 10rem))` }}>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Coverage</span><strong className="num">{formatPct(h.coverage)}</strong></div>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Akurasi</span><strong className="num">{formatPct(h.accuracy)}</strong></div>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Ambang</span><strong className="num">{h.threshold.toFixed(3)}</strong></div>
          </div>
        )}
      </div>
    </ChartFrame>
  )
}

/** Confusion matrix as a one-hue sequential heat table (counts printed in each cell). */
export function ConfusionMatrix({ labels, matrix, names }: { labels: string[]; matrix: number[][]; names: Record<string, string> }) {
  const max = Math.max(1, ...matrix.flat())
  return (
    <table className="text-sm" aria-label="Matriks konfusi">
      <thead>
        <tr><th className="p-1 text-left text-xs font-medium text-ink-2">Aktual ↓ / Prediksi →</th>{labels.map((l) => <th key={l} className="p-1 text-xs font-medium text-ink-2">{names[l] ?? l}</th>)}</tr>
      </thead>
      <tbody>
        {matrix.map((row, i) => (
          <tr key={labels[i]}>
            <th className="p-1 text-left text-xs font-medium text-ink-2">{names[labels[i]] ?? labels[i]}</th>
            {row.map((v, j) => {
              const t = v / max
              return (
                <td key={j} className="p-0.5">
                  <div className={cn('num grid h-11 w-16 place-items-center rounded-md text-sm', t > 0.55 ? 'font-semibold text-white' : 'text-ink')}
                    style={{ background: `color-mix(in oklab, var(--t-seq-1) ${Math.round(8 + t * 82)}%, var(--t-seq-0))` }}
                    title={`${names[labels[i]]} → ${names[labels[j]]}: ${v}`}>
                    {v}
                  </div>
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Dumbbell: one row per field, clean vs degraded F1 (2 series). */
export function DumbbellChart({ rows, names }: { rows: { field: string; clean: number; degraded: number }[]; names: Record<string, string> }) {
  const [tip, setTip] = useState<{ i: number } | null>(null)
  const rowH = 26
  const h = rows.length * rowH + 30
  const lo = Math.max(0, Math.floor(Math.min(...rows.map((r) => Math.min(r.clean, r.degraded))) * 10) / 10 - 0.05)
  const x = (v: number) => 130 + ((v - lo) / (1 - lo)) * (W - 130 - 20)
  return (
    <ChartFrame
      title="Ketahanan: F1 dokumen bersih vs terdegradasi (foto, scan, struk pudar)"
      legend={<><LegendKey color={SERIES[0]} label="Bersih" /><LegendKey color={SERIES[1]} label="Terdegradasi" /></>}
      table={
        <table className="w-full text-xs">
          <thead><tr className="text-left text-ink-2"><th className="py-1">Field</th><th className="text-right">Bersih</th><th className="text-right">Terdegradasi</th><th className="text-right">Selisih</th></tr></thead>
          <tbody className="num">{rows.map((r) => <tr key={r.field} className="border-t border-line"><td className="py-1">{names[r.field] ?? r.field}</td><td className="text-right">{r.clean.toFixed(3)}</td><td className="text-right">{r.degraded.toFixed(3)}</td><td className="text-right">{(r.degraded - r.clean).toFixed(3)}</td></tr>)}</tbody>
        </table>
      }
    >
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${h}`} className="w-full" role="img" aria-label="F1 per field, bersih dan terdegradasi">
          {[lo, (lo + 1) / 2, 1].map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={4} y2={h - 22} stroke="var(--t-line)" />
              <text x={x(t)} y={h - 8} textAnchor="middle" fontSize="10" fill="var(--t-muted)" className="num">{t.toFixed(2)}</text>
            </g>
          ))}
          {rows.map((r, i) => {
            const y = 14 + i * rowH
            return (
              <g key={r.field} tabIndex={0} onMouseEnter={() => setTip({ i })} onMouseLeave={() => setTip(null)} onFocus={() => setTip({ i })} onBlur={() => setTip(null)}>
                <rect x={0} y={y - rowH / 2} width={W} height={rowH} fill="transparent" />
                <text x={124} y={y + 3.5} textAnchor="end" fontSize="11" fill="var(--t-ink-2)">{names[r.field] ?? r.field}</text>
                <line x1={x(r.degraded)} x2={x(r.clean)} y1={y} y2={y} stroke="var(--t-line-strong)" strokeWidth="2" />
                <circle cx={x(r.clean)} cy={y} r={5} fill={SERIES[0]} stroke="var(--t-surface)" strokeWidth="2" />
                <circle cx={x(r.degraded)} cy={y} r={5} fill={SERIES[1]} stroke="var(--t-surface)" strokeWidth="2" />
              </g>
            )
          })}
        </svg>
        {tip && (
          <div className="pointer-events-none absolute right-2 top-2 rounded-md bg-surface px-2.5 py-1.5 text-xs shadow-lg ring-1 ring-line-strong">
            <p className="font-semibold text-ink">{names[rows[tip.i].field] ?? rows[tip.i].field}</p>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Bersih</span><strong className="num">{rows[tip.i].clean.toFixed(3)}</strong></div>
            <div className="flex justify-between gap-3"><span className="text-ink-2">Terdegradasi</span><strong className="num">{rows[tip.i].degraded.toFixed(3)}</strong></div>
          </div>
        )}
      </div>
    </ChartFrame>
  )
}

/** Horizontal bars for error categories (single series, one color). */
export function BarList({ title, rows }: { title: string; rows: { label: string; value: number; count: number }[] }) {
  const max = Math.max(0.0001, ...rows.map((r) => r.value))
  return (
    <ChartFrame title={title} table={
      <table className="w-full text-xs"><thead><tr className="text-left text-ink-2"><th className="py-1">Kategori</th><th className="text-right">Jumlah</th><th className="text-right">Porsi</th></tr></thead>
        <tbody className="num">{rows.map((r) => <tr key={r.label} className="border-t border-line"><td className="py-1">{r.label}</td><td className="text-right">{r.count}</td><td className="text-right">{formatPct(r.value)}</td></tr>)}</tbody></table>
    }>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.label} className="grid grid-cols-[minmax(8rem,14rem)_1fr_4.5rem] items-center gap-2 text-xs" title={`${r.label}: ${r.count}`}>
            <span className="truncate text-ink-2">{r.label}</span>
            <span className="h-3 rounded-r-[4px]" style={{ width: `${Math.max(1, (r.value / max) * 100)}%`, background: SERIES[0] }} />
            <span className="num text-right text-ink">{formatPct(r.value)} <span className="text-ink-2">({r.count})</span></span>
          </li>
        ))}
      </ul>
    </ChartFrame>
  )
}

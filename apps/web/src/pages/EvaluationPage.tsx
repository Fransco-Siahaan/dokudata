import { useMemo, useState } from 'react'
import { absolute, useApi } from '../api/client'
import { BarList, ConfusionMatrix, CoverageChart, DumbbellChart, ReliabilityChart, type Bin } from '../components/charts'
import { PageHeader } from '../components/Layout'
import { Card, EmptyState, Segmented } from '../components/ui'
import { DOC_TYPE_LABELS, FIELD_LABELS, cn, formatPct } from '../lib/format'

interface FieldScore { f1: number; precision: number; recall: number; ci?: [number, number] }
interface MethodRow {
  subset: string; engine: string; n: number
  fields: Record<string, FieldScore>; line_items: FieldScore
  doc_required: number; doc_exact: number; vendor_similarity?: number
  latency_p50_ms: number | null; latency_p95_ms: number | null; cost_per_doc: number | null
}
interface Summary {
  run_id: string
  created_at: string
  dataset: { name: string; seed: number; splits: Record<string, { n: number; digest: string }> }
  notes: string[]
  headline: Record<string, number | null>
  targets: { metric: string; target: string; stretch: string; value: string; met: boolean | null }[]
  extraction: { subsets: string[]; methods: { engine: string; label: string; available: boolean; note?: string }[]; rows: MethodRow[] }
  ocr: { engine: string; subset: string; preprocess: boolean; n: number; cer: number; wer: number; ms_per_page: number }[]
  classification: { methods: { name: string; subset: string; accuracy: number; macro_f1: number; labels: string[]; confusion_matrix: number[][] }[] }
  confidence: {
    methods: { name: string; ece: number; bins: Bin[] }[]
    coverage: { name: string; points: { threshold: number; coverage: number; accuracy: number }[] }[]
    decision: { field_threshold: number; classifier_threshold: number; automation_rate: number; auto_accuracy: number | null; n_docs: number; n_auto: number; target: number; by_subset?: Record<string, { n_docs: number; n_auto: number; automation_rate: number; auto_accuracy: number | null }> }
  }
  robustness: { engine: string; field: string; clean: number; degraded: number }[]
  injection: { n: number; detected_rate: number; forced_review_rate: number; auto_approved: number; by_engine: Record<string, { total_correct_rate: number; flagged_by_model_rate?: number }> }
  errors: { engine: string; categories: { category: string; label: string; count: number; share: number }[]; examples: { doc_id: string; subset: string; field: string; pred: string; gt: string; category: string; image: string | null }[] }
  system: { n: number; stages: Record<string, { p50: number; p95: number }>; total: { p50: number; p95: number } }
}

const SUBSET_LABELS: Record<string, string> = {
  'test_seen/clean': 'Templat dikenal · bersih',
  'test_seen/degraded': 'Templat dikenal · terdegradasi',
  'test_unseen/clean': 'Templat & vendor baru · bersih',
  'test_unseen/degraded': 'Templat & vendor baru · terdegradasi',
  all: 'Semua data uji',
}
const ENGINE_NAMES: Record<string, string> = { rules: 'A · OCR + aturan', llm_ocr: 'B · OCR + LLM', llm_vision: 'C · LLM visi' }
const FIELDS = ['vendor_name', 'issue_date', 'total', 'document_number', 'vendor_tax_id', 'subtotal', 'tax_amount', 'discount', 'due_date', 'payment_method']
const ms = (v: number | null | undefined) => (v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`)
const f3 = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(3))

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl bg-surface p-4 ring-1 ring-line">
      <p className="text-xs text-ink-2">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-2">{hint}</p>}
    </div>
  )
}

export function EvaluationPage() {
  const { data: s, error } = useApi<Summary>('/evaluation/summary')
  const [subset, setSubset] = useState('all')
  const rows = useMemo(() => (s?.extraction.rows ?? []).filter((r) => r.subset === subset), [s, subset])
  if (error) return <EmptyState title="Laporan evaluasi belum tersedia">{error.message}</EmptyState>
  if (!s) return <p className="text-ink-2" role="status">Memuat laporan…</p>
  const h = s.headline
  const bestCls = [...s.classification.methods].filter((m) => m.subset === 'all').sort((a, b) => b.macro_f1 - a.macro_f1)[0]
  const rulesErrors = s.errors

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evaluasi"
        description={<>Semua angka di halaman ini dihasilkan oleh <code>make evaluate</code> pada himpunan uji yang dibekukan (hash diverifikasi sebelum dijalankan). Run <code>{s.run_id}</code>, {new Date(s.created_at).toLocaleString('id-ID')}.</>}
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="F1 total (metode A)" value={formatPct(h.total_f1)} hint="Semua data uji, toleransi 0" />
        <Stat label="F1 field utama (vendor, tanggal, total)" value={formatPct(h.key_fields_f1)} />
        <Stat label="Klasifikasi jenis dokumen (macro-F1)" value={formatPct(h.classification_macro_f1)} />
        <Stat label="Dokumen lolos otomatis" value={formatPct(h.automation_rate)} hint={`Akurasi yang lolos: ${formatPct(h.auto_accuracy)}`} />
      </div>
      {s.notes.length > 0 && (
        <Card title="Catatan penting">
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">{s.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Card>
      )}

      <Card title="Kriteria sukses PRD (2.2)">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs text-ink-2"><tr><th className="py-1.5 font-medium">Metrik</th><th className="font-medium">Target MVP</th><th className="font-medium">Stretch</th><th className="font-medium">Hasil terukur</th><th className="font-medium">Status</th></tr></thead>
            <tbody className="divide-y divide-line">
              {s.targets.map((t) => (
                <tr key={t.metric}>
                  <td className="py-1.5 text-ink">{t.metric}</td><td className="text-ink-2">{t.target}</td><td className="text-ink-2">{t.stretch}</td>
                  <td className="num font-medium text-ink">{t.value}</td>
                  <td className={cn('text-xs font-medium', t.met === true ? 'text-good' : t.met === false ? 'text-bad' : 'text-ink-2')}>
                    {t.met === true ? '✓ tercapai' : t.met === false ? '✕ belum' : '· tidak diukur'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <section className="space-y-3" aria-labelledby="e4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="e4" className="text-base font-semibold text-ink">E4 · Perbandingan metode ekstraksi (F1 per field)</h2>
          <Segmented label="Subset data uji" value={subset} onChange={setSubset} options={['all', ...s.extraction.subsets].map((v) => ({ value: v, label: SUBSET_LABELS[v] ?? v }))} />
        </div>
        <div className="overflow-x-auto rounded-xl bg-surface ring-1 ring-line">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-2">
              <tr><th className="px-3 py-2 font-medium">Field</th>{rows.map((r) => <th key={r.engine} className="px-3 py-2 text-right font-medium">{ENGINE_NAMES[r.engine] ?? r.engine}<span className="block font-normal">n={r.n}</span></th>)}</tr>
            </thead>
            <tbody className="num divide-y divide-line">
              {FIELDS.map((f) => (
                <tr key={f}>
                  <td className="px-3 py-1.5 text-ink">{FIELD_LABELS[f]}</td>
                  {rows.map((r) => {
                    const v = r.fields[f]
                    const best = Math.max(...rows.map((x) => x.fields[f]?.f1 ?? 0))
                    return <td key={r.engine} className={cn('px-3 py-1.5 text-right', v && v.f1 === best && rows.length > 1 && 'font-semibold')} title={v?.ci ? `IK 95%: ${v.ci[0].toFixed(3)}–${v.ci[1].toFixed(3)}` : undefined}>{f3(v?.f1)}</td>
                  })}
                </tr>
              ))}
              <tr className="bg-surface-2"><td className="px-3 py-1.5 font-medium text-ink">Item baris (F1 baris)</td>{rows.map((r) => <td key={r.engine} className="px-3 py-1.5 text-right">{f3(r.line_items.f1)}</td>)}</tr>
              <tr><td className="px-3 py-1.5 text-ink">Dokumen: semua field wajib benar</td>{rows.map((r) => <td key={r.engine} className="px-3 py-1.5 text-right">{formatPct(r.doc_required)}</td>)}</tr>
              <tr><td className="px-3 py-1.5 text-ink">Dokumen: semua field + item benar</td>{rows.map((r) => <td key={r.engine} className="px-3 py-1.5 text-right">{formatPct(r.doc_exact)}</td>)}</tr>
              <tr><td className="px-3 py-1.5 text-ink">Latensi ekstraksi p50 / p95</td>{rows.map((r) => <td key={r.engine} className="px-3 py-1.5 text-right">{ms(r.latency_p50_ms)} / {ms(r.latency_p95_ms)}</td>)}</tr>
              <tr><td className="px-3 py-1.5 text-ink">Biaya per dokumen</td>{rows.map((r) => <td key={r.engine} className="px-3 py-1.5 text-right">{r.cost_per_doc == null ? '—' : r.cost_per_doc === 0 ? 'Rp 0 (lokal)' : `$${r.cost_per_doc.toFixed(4)}`}</td>)}</tr>
            </tbody>
          </table>
        </div>
        <ul className="text-xs text-ink-2">
          {s.extraction.methods.filter((m) => !m.available).map((m) => <li key={m.engine}>· {m.label}: {m.note ?? 'tidak dijalankan pada run ini'}</li>)}
        </ul>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <ReliabilityChart series={s.confidence.methods} />
        {s.confidence.coverage[0] && (
          <CoverageChart points={s.confidence.coverage[0].points} target={s.confidence.decision.target}
            chosen={s.confidence.decision.auto_accuracy != null ? { coverage: s.confidence.decision.automation_rate, accuracy: s.confidence.decision.auto_accuracy } : null} />
        )}
      </div>
      <p className="-mt-2 text-xs text-ink-2">
        E5 · Ambang dipilih pada data validasi: keyakinan field ≥ {s.confidence.decision.field_threshold}, keyakinan jenis ≥ {s.confidence.decision.classifier_threshold}.
        Pada data uji: {s.confidence.decision.n_auto} dari {s.confidence.decision.n_docs} nota/faktur lolos otomatis ({formatPct(s.confidence.decision.automation_rate)}), akurasi {formatPct(s.confidence.decision.auto_accuracy)}.
      </p>
      {s.confidence.decision.by_subset && (
        <div className="overflow-x-auto rounded-xl bg-surface ring-1 ring-line">
          <table className="w-full min-w-[520px] text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-2"><tr><th className="px-3 py-2 font-medium">Subset</th><th className="px-3 py-2 text-right font-medium">Nota/faktur</th><th className="px-3 py-2 text-right font-medium">Lolos otomatis</th><th className="px-3 py-2 text-right font-medium">Akurasi yang lolos</th></tr></thead>
            <tbody className="num divide-y divide-line">
              {Object.entries(s.confidence.decision.by_subset).map(([k, v]) => (
                <tr key={k}><td className="px-3 py-1.5 text-ink">{SUBSET_LABELS[k] ?? k}</td><td className="px-3 py-1.5 text-right">{v.n_docs}</td><td className="px-3 py-1.5 text-right">{formatPct(v.automation_rate)}</td>
                  <td className={cn('px-3 py-1.5 text-right', v.auto_accuracy != null && v.auto_accuracy < s.confidence.decision.target && 'text-bad')}>{formatPct(v.auto_accuracy)}{v.auto_accuracy != null && v.auto_accuracy < s.confidence.decision.target ? ' ✕' : ''}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <DumbbellChart rows={s.robustness.filter((r) => r.engine === 'rules')} names={{ ...FIELD_LABELS }} />
        {bestCls && (
          <Card title={`E3 · Klasifikasi jenis dokumen`}>
            <table className="mb-4 w-full text-sm">
              <thead className="text-left text-xs text-ink-2"><tr><th className="py-1 font-medium">Metode</th><th className="text-right font-medium">Akurasi</th><th className="text-right font-medium">Macro-F1 (semua)</th><th className="text-right font-medium">Macro-F1 (templat baru)</th></tr></thead>
              <tbody className="num divide-y divide-line">
                {[...new Set(s.classification.methods.map((m) => m.name))].map((name) => {
                  const all = s.classification.methods.find((m) => m.name === name && m.subset === 'all')
                  const unseen = s.classification.methods.find((m) => m.name === name && m.subset === 'test_unseen')
                  return <tr key={name}><td className="py-1 text-ink">{name}</td><td className="text-right">{formatPct(all?.accuracy)}</td><td className="text-right">{f3(all?.macro_f1)}</td><td className="text-right">{f3(unseen?.macro_f1)}</td></tr>
                })}
              </tbody>
            </table>
            <p className="mb-2 text-xs text-ink-2">Matriks konfusi: {bestCls.name}, semua data uji</p>
            <ConfusionMatrix labels={bestCls.labels} matrix={bestCls.confusion_matrix} names={DOC_TYPE_LABELS} />
          </Card>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="E1 & E2 · OCR dan pra-proses (CER/WER, lebih kecil lebih baik)">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead className="text-left text-xs text-ink-2"><tr><th className="py-1 font-medium">Mesin</th><th className="font-medium">Subset</th><th className="font-medium">Pra-proses</th><th className="text-right font-medium">CER</th><th className="text-right font-medium">WER</th><th className="text-right font-medium">Waktu/hal.</th></tr></thead>
              <tbody className="num divide-y divide-line">
                {s.ocr.map((o) => (
                  <tr key={`${o.engine}-${o.subset}-${o.preprocess}`}><td className="py-1 text-ink">{o.engine}</td><td className="text-ink-2">{o.subset}</td><td>{o.preprocess ? 'ya' : 'tidak'}</td><td className="text-right">{f3(o.cer)}</td><td className="text-right">{f3(o.wer)}</td><td className="text-right">{ms(o.ms_per_page)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Keselamatan AI · dokumen berisi prompt injection">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-xs text-ink-2">Dokumen uji</dt><dd className="text-xl font-semibold">{s.injection.n}</dd></div>
            <div><dt className="text-xs text-ink-2">Terdeteksi oleh pemindai</dt><dd className="text-xl font-semibold">{formatPct(s.injection.detected_rate)}</dd></div>
            <div><dt className="text-xs text-ink-2">Dipaksa ke tinjauan manusia</dt><dd className="text-xl font-semibold">{formatPct(s.injection.forced_review_rate)}</dd></div>
            <div><dt className="text-xs text-ink-2">Lolos otomatis</dt><dd className="text-xl font-semibold">{s.injection.auto_approved}</dd></div>
          </dl>
          <ul className="mt-3 space-y-1 text-xs text-ink-2">
            {Object.entries(s.injection.by_engine).map(([e, v]) => (
              <li key={e}>{ENGINE_NAMES[e] ?? e}: total tetap benar pada {formatPct(v.total_correct_rate)} dokumen{v.flagged_by_model_rate != null ? `; model menandai instruksi mencurigakan pada ${formatPct(v.flagged_by_model_rate)}` : ''}</li>
            ))}
          </ul>
        </Card>
      </div>

      <section className="space-y-3" aria-labelledby="errors">
        <h2 id="errors" className="text-base font-semibold text-ink">Analisis kesalahan ({ENGINE_NAMES[rulesErrors.engine] ?? rulesErrors.engine})</h2>
        <BarList title="Kategori kesalahan field" rows={rulesErrors.categories.map((c) => ({ label: c.label, value: c.share, count: c.count }))} />
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {rulesErrors.examples.map((x, i) => (
            <li key={`${x.doc_id}-${x.field}-${i}`} className="rounded-xl bg-surface p-3 ring-1 ring-line">
              {x.image && <img src={absolute(`/api/v1/evaluation/assets/${x.image}`)} alt={`Potongan ${x.doc_id} di sekitar ${FIELD_LABELS[x.field] ?? x.field}`} className="mb-2 max-h-40 w-full rounded bg-surface-2 object-contain ring-1 ring-line" loading="lazy" />}
              <p className="text-xs text-ink-2">{x.doc_id} · {SUBSET_LABELS[x.subset] ?? x.subset}</p>
              <p className="text-sm font-medium text-ink">{FIELD_LABELS[x.field] ?? x.field} · {rulesErrors.categories.find((c) => c.category === x.category)?.label ?? x.category}</p>
              <p className="mt-1 text-xs"><span className="text-ink-2">Prediksi:</span> <span className="text-bad">{x.pred || '∅'}</span></p>
              <p className="text-xs"><span className="text-ink-2">Benar:</span> <span className="text-good">{x.gt || '∅'}</span></p>
            </li>
          ))}
        </ul>
      </section>

      <Card title={`Latensi sistem end-to-end (${s.system.n} dokumen, CPU, satu halaman)`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-sm">
            <thead className="text-left text-xs text-ink-2"><tr><th className="py-1 font-medium">Tahap</th><th className="text-right font-medium">p50</th><th className="text-right font-medium">p95</th></tr></thead>
            <tbody className="num divide-y divide-line">
              {Object.entries(s.system.stages).map(([k, v]) => <tr key={k}><td className="py-1 text-ink">{k}</td><td className="text-right">{ms(v.p50)}</td><td className="text-right">{ms(v.p95)}</td></tr>)}
              <tr className="font-semibold"><td className="py-1">Total</td><td className="text-right">{ms(s.system.total.p50)}</td><td className="text-right">{ms(s.system.total.p95)}</td></tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Data">
        <p className="text-sm text-ink-2">
          {s.dataset.name}, seed {s.dataset.seed}. Seluruh dokumen sintetis (nama, NPWP, dan alamat palsu). Hasil pada data nyata belum diukur; lihat laporan evaluasi untuk keterbatasan.
        </p>
        <ul className="mt-2 grid gap-1 text-xs text-ink-2 sm:grid-cols-2">
          {Object.entries(s.dataset.splits).map(([k, v]) => <li key={k} className="num">{k}: n={v.n} · sha256 {v.digest.slice(0, 12)}…</li>)}
        </ul>
      </Card>
    </div>
  )
}

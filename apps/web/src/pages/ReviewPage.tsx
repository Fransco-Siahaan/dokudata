import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, absolute, api, useApi } from '../api/client'
import type { DocumentDetail, DocumentList, Engine, Finding, Health, LineItem, Values } from '../api/types'
import {
  Button, Card, ConfidenceBadge, ConfirmDialog, Kbd, SelectField, StatusBadge, TextInput, inputClass, notify,
} from '../components/ui'
import {
  DOC_TYPE_LABELS, ENGINE_LABELS, FIELD_LABELS, PAYMENT_LABELS, cn, formatNumber, formatRupiah, parseAmountInput,
} from '../lib/format'
import { Link, navigate } from '../lib/router'
import { ENGINES, LLM_SETUP_HINT } from '../lib/engines'
import { isTerminal, useDocumentEvents } from '../lib/useDocumentEvents'

const HEADER = ['vendor_name', 'issue_date', 'total', 'document_number', 'vendor_tax_id', 'due_date', 'subtotal', 'discount', 'tax_amount', 'payment_method', 'currency']
const AMOUNTS = new Set(['subtotal', 'discount', 'tax_amount', 'total'])
const REQUIRED = new Set(['vendor_name', 'issue_date', 'total', 'currency'])
const DEFAULT_THRESHOLD = 0.9

type Form = Record<string, string>
interface ItemRow { description: string; qty: string; unit_price: string; amount: string }

const toStr = (v: unknown) => (v == null ? '' : String(v))
const amountStr = (v: unknown) => (v == null || v === '' ? '' : formatNumber(Number(v)))

function initialForm(values: Values | null): Form {
  const f: Form = {}
  for (const k of HEADER) f[k] = AMOUNTS.has(k) ? amountStr(values?.[k]) : toStr(values?.[k])
  if (!f.currency) f.currency = 'IDR'
  return f
}

function initialItems(values: Values | null): ItemRow[] {
  return (values?.line_items ?? []).map((li: LineItem) => ({
    description: toStr(li.description), qty: toStr(li.qty), unit_price: amountStr(li.unit_price), amount: amountStr(li.amount),
  }))
}

function close(a: number, b: number) {
  return Math.abs(a - b) <= Math.max(1, 0.001 * Math.max(Math.abs(a), Math.abs(b)))
}

export function ReviewPage({ id }: { id: string }) {
  const { data: doc, error, reload, setData } = useApi<DocumentDetail>(`/documents/${id}`)
  const queue = useApi<DocumentList>('/documents?status=needs_review&limit=500')
  const live = useDocumentEvents(doc?.events_url ?? null, doc?.status ?? 'queued')

  useEffect(() => {
    if (doc && !isTerminal(doc.status) && isTerminal(live.status)) void reload()
  }, [live.status, doc, reload])

  if (error) return <p className="text-bad">{error.message} · <Link href="/dokumen" className="underline">kembali</Link></p>
  if (!doc) return <p className="text-ink-2" role="status">Memuat dokumen…</p>
  if (!isTerminal(doc.status)) {
    return (
      <Card title={doc.original_name}>
        <p className="flex items-center gap-2 text-sm text-ink-2" role="status">
          <StatusBadge status={live.status} /> Dokumen sedang diproses; halaman ini akan diperbarui otomatis.
        </p>
      </Card>
    )
  }
  if (doc.status === 'failed') {
    return (
      <Card title={doc.original_name}>
        <p className="text-sm text-bad">Gagal diproses: {doc.error}</p>
        <Reprocess doc={doc} onDone={(d) => setData(d)} />
      </Card>
    )
  }
  const ids = queue.data?.items.map((d) => d.id) ?? []
  return <Reviewer key={`${doc.id}-${doc.reviews}-${doc.engine}-${doc.status}`} doc={doc} queueIds={ids} onSaved={(d) => setData(d)} />
}

function Reprocess({ doc, onDone }: { doc: DocumentDetail; onDone: (d: DocumentDetail) => void }) {
  const [engine, setEngine] = useState<Engine>(doc.engine)
  const [busy, setBusy] = useState(false)
  const llm = useApi<Health>('/health').data?.llm_configured ?? false
  return (
    <div className="mt-3 flex flex-wrap items-end gap-2">
      <SelectField className="w-56" label="Proses ulang dengan" value={engine} onChange={(v) => setEngine(v as Engine)}
        options={ENGINES.map((e) => ({ value: e.id, label: `${e.code} · ${e.name}${e.needsLlm && !llm ? ' (belum aktif)' : ''}`, disabled: e.needsLlm && !llm }))} />
      <Button variant="secondary" loading={busy} onClick={async () => {
        setBusy(true)
        try {
          onDone(await api<DocumentDetail>(`/documents/${doc.id}/reprocess`, { method: 'POST', body: JSON.stringify({ engine }) }))
        } catch (e) {
          notify.error(e)
        } finally {
          setBusy(false)
        }
      }}>
        Proses ulang
      </Button>
      {!llm && <p className="basis-full text-xs text-ink-2">{LLM_SETUP_HINT}</p>}
    </div>
  )
}

function Reviewer({ doc, queueIds, onSaved }: { doc: DocumentDetail; queueIds: string[]; onSaved: (d: DocumentDetail) => void }) {
  const result = doc.result
  const ex = result?.extraction
  // Same threshold the decision used, so a field shown as "yakin" really cleared the gate.
  const THRESHOLD = result?.thresholds?.field ?? DEFAULT_THRESHOLD
  const [form, setForm] = useState<Form>(() => initialForm(doc.data))
  const [items, setItems] = useState<ItemRow[]>(() => initialItems(doc.data))
  const [docType, setDocType] = useState(doc.doc_type ?? 'receipt')
  const [selected, setSelected] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [saving, setSaving] = useState(false)
  const [serverIssues, setServerIssues] = useState<Finding[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const inputs = useRef<Record<string, HTMLInputElement | null>>({})

  const findings = useMemo(() => result?.validation ?? [], [result])
  const problemFields = useMemo(() => {
    const s = new Set<string>()
    for (const f of findings) if (f.status === 'warning' || f.status === 'fail') f.fields.forEach((x) => s.add(x))
    for (const k of HEADER) {
      const c = ex?.[k]?.confidence
      if (c != null && c < THRESHOLD) s.add(k)
      if (REQUIRED.has(k) && !form[k]) s.add(k)
    }
    return s
  }, [findings, ex, form, THRESHOLD])
  const ordered = useMemo(() => [...HEADER].sort((a, b) => Number(problemFields.has(b)) - Number(problemFields.has(a))), [problemFields])
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? ordered : ordered.filter((k) => problemFields.has(k) || REQUIRED.has(k))

  // Live arithmetic checks while the reviewer edits.
  const n = (k: string) => parseAmountInput(form[k] ?? '')
  const itemSum = items.reduce((s, it) => s + (parseAmountInput(it.amount) ?? 0), 0)
  const checks: { ok: boolean | null; text: string }[] = [
    { ok: items.length === 0 ? null : n('subtotal') != null ? close(itemSum, n('subtotal')!) : (!n('tax_amount') && !n('discount') && n('total') != null) ? close(itemSum, n('total')!) : null,
      text: `Jumlah item ${formatRupiah(itemSum)}` },
    { ok: n('subtotal') != null && n('total') != null ? close(n('subtotal')! - Math.abs(n('discount') ?? 0) + (n('tax_amount') ?? 0), n('total')!) : null,
      text: 'Subtotal − diskon + pajak = total' },
  ]

  const values = useCallback((): Values => {
    const v: Values = { line_items: [] }
    for (const k of HEADER) v[k] = AMOUNTS.has(k) ? parseAmountInput(form[k]) : form[k].trim() || null
    v.line_items = items
      .filter((it) => it.description.trim() || it.amount.trim())
      .map((it) => ({ description: it.description.trim() || null, qty: it.qty ? Number(it.qty.replace(',', '.')) : null,
        unit_price: parseAmountInput(it.unit_price), amount: parseAmountInput(it.amount) }))
    return v
  }, [form, items])

  const idx = queueIds.indexOf(doc.id)
  const nextId = queueIds.find((x) => x !== doc.id && (idx < 0 || queueIds.indexOf(x) > idx)) ?? queueIds.find((x) => x !== doc.id)
  const prevId = idx > 0 ? queueIds[idx - 1] : undefined

  const save = useCallback(async (goNext: boolean) => {
    setSaving(true)
    setServerIssues([])
    try {
      const res = await api<{ document: DocumentDetail; changed_fields: string[] }>(`/documents/${doc.id}/review`, {
        method: 'PATCH', body: JSON.stringify({ data: values(), doc_type: docType }),
      })
      notify.success('Tersimpan sebagai sudah ditinjau', res.changed_fields.length ? `${res.changed_fields.length} field dikoreksi` : 'Tanpa perubahan')
      if (goNext && nextId) navigate(`/dokumen/${nextId}`)
      else onSaved(res.document)
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && typeof e.detail === 'object' && e.detail && 'validation' in e.detail) {
        setServerIssues((e.detail as { validation: Finding[] }).validation)
      }
      notify.error(e)
    } finally {
      setSaving(false)
    }
  }, [doc.id, values, docType, nextId, onSaved])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault()
        void save(true)
      } else if (e.altKey && e.key === 'ArrowRight' && nextId) {
        navigate(`/dokumen/${nextId}`)
      } else if (e.altKey && e.key === 'ArrowLeft' && prevId) {
        navigate(`/dokumen/${prevId}`)
      } else if (e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault()
        const probs = ordered.filter((k) => problemFields.has(k))
        if (!probs.length) return
        const cur = selected ? probs.indexOf(selected) : -1
        const nxt = probs[(cur + (e.key === 'ArrowDown' ? 1 : probs.length - 1)) % probs.length]
        setSelected(nxt)
        inputs.current[nxt]?.focus()
      } else if (!typing && (e.key === '+' || e.key === '=')) {
        setZoom((z) => Math.min(3, z + 0.25))
      } else if (!typing && e.key === '-') {
        setZoom((z) => Math.max(0.5, z - 0.25))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [save, nextId, prevId, ordered, problemFields, selected])

  // Highlight boxes: the selected field, plus the problem fields in a lighter outline.
  const boxes = useMemo(() => {
    const out: { key: string; bbox: number[]; page: number; label: string; problem: boolean }[] = []
    for (const k of HEADER) {
      const fv = ex?.[k]
      if (fv?.bbox) out.push({ key: k, bbox: fv.bbox, page: fv.page ?? 0, label: FIELD_LABELS[k], problem: problemFields.has(k) })
    }
    ex?.line_items?.forEach((li, i) => {
      // Item boxes only appear when their row is selected, to keep the page readable.
      if (li.bbox) out.push({ key: `item:${i}`, bbox: li.bbox, page: li.page ?? 0, label: `Item ${i + 1}`, problem: false })
    })
    return out
  }, [ex, problemFields])

  const pg = doc.pages[page]
  const selectedBox = boxes.find((b) => b.key === selected)
  useEffect(() => {
    if (selectedBox && selectedBox.page !== page && doc.pages[selectedBox.page]) setPage(selectedBox.page)
  }, [selectedBox, page, doc.pages])

  const deleteDoc = async () => {
    try {
      await api(`/documents/${doc.id}`, { method: 'DELETE' })
      notify.success('Dokumen dihapus')
      navigate(nextId ? `/dokumen/${nextId}` : '/dokumen')
    } catch (e) {
      notify.error(e)
    }
  }

  const issues = [...findings.filter((f) => f.status === 'warning' || f.status === 'fail'), ...serverIssues]
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Link href="/dokumen" className="text-sm text-ink-2 hover:text-ink">← Dokumen</Link>
        <h1 className="min-w-0 flex-1 truncate text-lg font-semibold text-ink">{doc.original_name}</h1>
        <StatusBadge status={doc.status} />
        <span className="text-xs text-ink-2">{ENGINE_LABELS[doc.engine]}{result?.engines.llm_model ? ` · ${result.engines.llm_model}` : ''}{result?.engines.cross_check ? ' · dicek silang metode A' : ''}{result?.cost_usd ? ` · biaya ${result.cost_usd.toFixed(4)} USD` : ''}</span>
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" disabled={!prevId} onClick={() => prevId && navigate(`/dokumen/${prevId}`)} aria-label="Dokumen sebelumnya">‹</Button>
          <Button size="sm" variant="ghost" disabled={!nextId} onClick={() => nextId && navigate(`/dokumen/${nextId}`)} aria-label="Dokumen berikutnya">›</Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {/* Left: page image with highlight boxes */}
        <section aria-label="Gambar dokumen" className="rounded-xl bg-surface ring-1 ring-line">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-sm">
            <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} aria-label="Perkecil">−</Button>
            <span className="num w-12 text-center text-xs text-ink-2">{Math.round(zoom * 100)}%</span>
            <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.min(3, z + 0.25))} aria-label="Perbesar">+</Button>
            <Button size="sm" variant="ghost" onClick={() => setZoom(1)}>Pas</Button>
            {doc.pages.length > 1 && (
              <span className="ml-2 flex items-center gap-1 text-xs text-ink-2">
                Halaman
                {doc.pages.map((p, i) => (
                  <button key={p.number} onClick={() => setPage(i)} aria-current={i === page}
                    className={cn('rounded px-2 py-0.5', i === page ? 'bg-brand text-brand-ink' : 'ring-1 ring-line')}>{p.number}</button>
                ))}
              </span>
            )}
            <a href={absolute(doc.original_url)} target="_blank" rel="noreferrer" className="ml-auto text-xs text-brand underline">Berkas asli</a>
          </div>
          <div className="max-h-[78vh] overflow-auto bg-surface-2 p-3">
            {pg && (
              <div className="relative mx-auto" style={{ width: `${zoom * 100}%` }}>
                <img src={absolute(pg.url)} alt={`Halaman ${pg.number} dari ${doc.original_name}`} className="block w-full shadow-sm" />
                <svg viewBox={`0 0 ${pg.width} ${pg.height}`} className="absolute inset-0 size-full" aria-hidden>
                  {boxes.filter((b) => b.page === page).map((b) => {
                    const sel = b.key === selected
                    if (!sel && !b.problem) return null
                    const [x0, y0, x1, y1] = b.bbox
                    return (
                      <rect key={b.key} x={x0 - 4} y={y0 - 4} width={x1 - x0 + 8} height={y1 - y0 + 8} rx={4}
                        className="cursor-pointer" style={{ pointerEvents: 'all' }}
                        fill={sel ? 'color-mix(in srgb, var(--t-brand) 18%, transparent)' : 'transparent'}
                        stroke={sel ? 'var(--t-brand)' : 'var(--t-warn)'} strokeWidth={sel ? 4 : 2.5}
                        onClick={() => { setSelected(b.key); if (!b.key.startsWith('item:')) inputs.current[b.key]?.focus() }} />
                    )
                  })}
                </svg>
              </div>
            )}
          </div>
          {pg?.preprocess?.length ? <p className="border-t border-line px-3 py-2 text-xs text-ink-2">Pra-proses: {pg.preprocess.join(' · ')}</p> : null}
        </section>

        {/* Right: decision, fields, items */}
        <div className="space-y-4">
          {result && (
            <Card title="Keputusan sistem">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span>Jenis: <strong>{DOC_TYPE_LABELS[result.document_type.value as string] ?? '—'}</strong></span>
                <ConfidenceBadge value={result.document_type.confidence} />
                <span className="text-ink-2">Keyakinan dokumen</span>
                <ConfidenceBadge value={result.document_confidence} />
              </div>
              {result.decision_reasons.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm">
                  {result.decision_reasons.map((r, i) => (
                    <li key={i} className="flex gap-2"><span aria-hidden className="text-warn">!</span><span className="text-ink">{r}</span></li>
                  ))}
                </ul>
              )}
              {result.decision === 'auto_approved' && <p className="mt-2 text-sm text-good">✓ Semua pemeriksaan lolos; dokumen siap diekspor.</p>}
            </Card>
          )}

          <Card title="Field" actions={
            <label className="flex items-center gap-2 text-xs text-ink-2">
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
              Tampilkan semua ({HEADER.length})
            </label>
          }>
            <SelectField className="mb-3 max-w-56" label="Jenis dokumen" value={docType} onChange={setDocType}
              options={Object.entries(DOC_TYPE_LABELS).map(([value, label]) => ({ value, label }))} />
            <div className="space-y-2.5">
              {visible.map((k) => {
                const fv = ex?.[k]
                const problem = problemFields.has(k)
                return (
                  <div key={k} className={cn('grid grid-cols-[8.5rem_1fr] items-center gap-2 rounded-lg px-2 py-1.5', problem && 'bg-warn-soft', selected === k && 'ring-2 ring-brand')}>
                    <label htmlFor={`f-${k}`} className="text-xs font-medium text-ink-2">
                      {FIELD_LABELS[k]}{REQUIRED.has(k) && <span aria-label="wajib" className="text-bad"> *</span>}
                    </label>
                    <div className="flex items-center gap-2">
                      {k === 'payment_method' ? (
                        <select id={`f-${k}`} className={inputClass} value={form[k]} onFocus={() => setSelected(k)}
                          onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}>
                          <option value="">—</option>
                          {Object.entries(PAYMENT_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                      ) : (
                        <TextInput id={`f-${k}`} ref={(el) => { inputs.current[k] = el }} value={form[k]}
                          type={k.endsWith('_date') ? 'date' : 'text'} inputMode={AMOUNTS.has(k) ? 'decimal' : undefined}
                          aria-invalid={problem} onFocus={() => setSelected(k)}
                          onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
                          className={AMOUNTS.has(k) ? 'num text-right' : undefined} />
                      )}
                      <div className="w-32 shrink-0 text-right"><ConfidenceBadge value={fv?.confidence ?? null} threshold={THRESHOLD} /></div>
                    </div>
                  </div>
                )
              })}
            </div>
            {!showAll && <p className="mt-2 text-xs text-ink-2">{HEADER.length - visible.length} field lain terbaca dengan yakin.</p>}
          </Card>

          <Card title={`Item baris (${items.length})`} actions={
            <Button size="sm" variant="secondary" onClick={() => setItems((it) => [...it, { description: '', qty: '1', unit_price: '', amount: '' }])}>+ Baris</Button>
          }>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead className="text-left text-xs text-ink-2">
                  <tr><th className="pb-1 font-medium">Deskripsi</th><th className="w-16 pb-1 font-medium">Qty</th><th className="w-28 pb-1 font-medium">Harga</th><th className="w-28 pb-1 font-medium">Jumlah</th><th className="w-8" /></tr>
                </thead>
                <tbody>
                  {items.map((it, i) => {
                    const q = Number(it.qty.replace(',', '.'))
                    const p = parseAmountInput(it.unit_price)
                    const a = parseAmountInput(it.amount)
                    const bad = Boolean(q) && p != null && a != null && !close(q * p, a)
                    return (
                      <tr key={i} className={cn(selected === `item:${i}` && 'bg-brand-soft')} onFocus={() => setSelected(`item:${i}`)}>
                        {(['description', 'qty', 'unit_price', 'amount'] as const).map((col) => (
                          <td key={col} className="py-0.5 pr-1">
                            <input aria-label={`${col === 'description' ? 'Deskripsi' : col === 'qty' ? 'Qty' : col === 'unit_price' ? 'Harga satuan' : 'Jumlah'} baris ${i + 1}`}
                              className={cn(inputClass, 'h-8', col !== 'description' && 'num text-right', bad && col === 'amount' && 'ring-bad')}
                              value={it[col]} onChange={(e) => setItems((rows) => rows.map((r, j) => (j === i ? { ...r, [col]: e.target.value } : r)))} />
                          </td>
                        ))}
                        <td><button className="px-2 text-muted hover:text-bad" aria-label={`Hapus baris ${i + 1}`} onClick={() => setItems((rows) => rows.filter((_, j) => j !== i))}>×</button></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <ul className="mt-3 space-y-1 text-xs">
              {checks.map((c) => (
                <li key={c.text} className={cn('flex gap-2', c.ok === false ? 'text-bad' : c.ok ? 'text-good' : 'text-ink-2')}>
                  <span aria-hidden>{c.ok === false ? '✕' : c.ok ? '✓' : '·'}</span>
                  {c.text}{c.ok === false ? ' — tidak cocok' : c.ok ? ' — cocok' : ' — belum bisa dicek'}
                </li>
              ))}
            </ul>
          </Card>

          {issues.length > 0 && (
            <Card title="Temuan validasi">
              <ul className="space-y-1.5 text-sm">
                {issues.map((f, i) => (
                  <li key={`${f.rule}-${i}`} className="flex gap-2">
                    <span aria-hidden className={f.status === 'fail' ? 'text-bad' : 'text-warn'}>{f.status === 'fail' ? '✕' : '!'}</span>
                    <span><span className="font-medium text-ink">{f.status === 'fail' ? 'Gagal' : 'Peringatan'}:</span> <span className="text-ink-2">{f.detail || f.rule}</span></span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-2 rounded-xl bg-surface/95 p-3 ring-1 ring-line backdrop-blur">
            <Button onClick={() => void save(true)} loading={saving}>Simpan &amp; tandai benar</Button>
            <Button variant="secondary" onClick={() => void save(false)} disabled={saving}>Simpan</Button>
            <Button variant="ghost" onClick={() => setConfirmDelete(true)}>Hapus</Button>
            <p className="ml-auto hidden text-xs text-ink-2 md:block">
              <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd> simpan &amp; lanjut · <Kbd>Alt</Kbd>+<Kbd>↓</Kbd> field bermasalah · <Kbd>Alt</Kbd>+<Kbd>→</Kbd> dokumen berikut · <Kbd>+</Kbd>/<Kbd>−</Kbd> zoom
            </p>
          </div>
          <Reprocess doc={doc} onDone={onSaved} />
        </div>
      </div>
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} danger title="Hapus dokumen ini?"
        description="Berkas dan semua hasil turunannya dihapus permanen." confirmLabel="Hapus" onConfirm={() => void deleteDoc()} />
    </div>
  )
}

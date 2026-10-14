import { useMemo, useState } from 'react'
import { api, useApi } from '../api/client'
import type { DocStatus, DocumentList } from '../api/types'
import { PageHeader } from '../components/Layout'
import { Button, ConfirmDialog, EmptyState, SelectField, StatusBadge, TextInput, notify, statusLabel } from '../components/ui'
import { DOC_TYPE_LABELS, ENGINE_LABELS, formatDate, formatRupiah } from '../lib/format'
import { Link, navigate, useLocation } from '../lib/router'

const STATUS_FILTERS: { value: string; label: string; statuses: DocStatus[] }[] = [
  { value: '', label: 'Semua status', statuses: [] },
  { value: 'review', label: 'Perlu tinjau', statuses: ['needs_review'] },
  { value: 'done', label: 'Siap ekspor', statuses: ['auto_approved', 'reviewed'] },
  { value: 'exported', label: 'Diekspor', statuses: ['exported'] },
  { value: 'processing', label: 'Sedang diproses', statuses: ['queued', 'preprocessing', 'ocr', 'classifying', 'extracting', 'validating'] },
  { value: 'rejected', label: 'Di luar cakupan', statuses: ['rejected'] },
  { value: 'failed', label: 'Gagal', statuses: ['failed'] },
]

export function DocumentsPage() {
  const { search } = useLocation()
  const [status, setStatus] = useState(search.get('status') ?? '')
  const [docType, setDocType] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirm, setConfirm] = useState(false)

  const path = useMemo(() => {
    const p = new URLSearchParams()
    STATUS_FILTERS.find((s) => s.value === status)?.statuses.forEach((s) => p.append('status', s))
    if (docType) p.set('doc_type', docType)
    if (from) p.set('date_from', from)
    if (to) p.set('date_to', to)
    if (q.trim()) p.set('q', q.trim())
    return `/documents?${p.toString()}`
  }, [status, docType, from, to, q])
  const list = useApi<DocumentList>(path)
  const items = list.data?.items ?? []
  const allSelected = items.length > 0 && items.every((d) => selected.has(d.id))

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  async function removeSelected() {
    try {
      await Promise.all([...selected].map((id) => api(`/documents/${id}`, { method: 'DELETE' })))
      notify.success(`${selected.size} dokumen dihapus`)
      setSelected(new Set())
      void list.reload()
    } catch (e) {
      notify.error(e)
    }
  }

  const counts = list.data?.counts ?? {}
  return (
    <div>
      <PageHeader
        title="Dokumen"
        description="Semua dokumen di sesi peramban ini. Dokumen yang perlu ditinjau diurutkan per tanggal unggah."
        actions={
          <Button onClick={() => navigate('/unggah')} size="sm">
            Unggah
          </Button>
        }
      />
      <div className="mb-3 flex flex-wrap gap-2 text-xs text-ink-2" aria-label="Ringkasan status">
        {Object.entries(counts).map(([s, n]) => (
          <span key={s} className="rounded-full bg-surface px-2 py-1 ring-1 ring-line">
            {statusLabel(s as DocStatus)}: <span className="num font-semibold text-ink">{n}</span>
          </span>
        ))}
      </div>
      <div className="mb-4 grid gap-3 rounded-xl bg-surface p-3 ring-1 ring-line sm:grid-cols-2 lg:grid-cols-5" role="search">
        <SelectField label="Status" value={status} onChange={setStatus} options={STATUS_FILTERS.map(({ value, label }) => ({ value, label }))} placeholder="Semua status" />
        <SelectField label="Jenis" value={docType} onChange={setDocType} placeholder="Semua jenis"
          options={[{ value: '', label: 'Semua jenis' }, ...Object.entries(DOC_TYPE_LABELS).map(([value, label]) => ({ value, label }))]} />
        <label className="flex flex-col gap-1 text-xs font-medium text-ink-2">
          Tanggal dari
          <TextInput type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-ink-2">
          Tanggal sampai
          <TextInput type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-ink-2">
          Cari vendor / nama berkas
          <TextInput value={q} onChange={(e) => setQ(e.target.value)} placeholder="mis. Toko Maju" />
        </label>
      </div>

      {selected.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-brand-soft px-3 py-2 text-sm" role="region" aria-label="Aksi massal">
          <span className="font-medium text-ink">{selected.size} dipilih</span>
          <Button size="sm" onClick={() => navigate(`/ekspor?ids=${[...selected].join(',')}`)}>
            Ekspor / arsipkan
          </Button>
          <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>
            Hapus
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Batal pilih
          </Button>
        </div>
      )}

      {list.error && <p className="text-sm text-bad">{list.error.message}</p>}
      {!list.loading && items.length === 0 ? (
        <EmptyState title="Belum ada dokumen">
          <Link href="/unggah" className="text-brand underline">Unggah dokumen</Link> atau <Link href="/" className="text-brand underline">coba contoh</Link>.
        </EmptyState>
      ) : (
        <div className={`overflow-x-auto rounded-xl bg-surface ring-1 ring-line ${list.loading ? 'opacity-60' : ''}`}>
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-line text-left text-xs text-ink-2">
              <tr>
                <th className="w-10 px-3 py-2">
                  <input type="checkbox" aria-label="Pilih semua" checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((d) => d.id)))} />
                </th>
                <th className="px-3 py-2 font-medium">Berkas</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Jenis</th>
                <th className="px-3 py-2 font-medium">Vendor</th>
                <th className="px-3 py-2 font-medium">Tanggal</th>
                <th className="px-3 py-2 text-right font-medium">Total</th>
                <th className="px-3 py-2 font-medium">Mesin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {items.map((d) => (
                <tr key={d.id} className="hover:bg-surface-2">
                  <td className="px-3 py-2">
                    <input type="checkbox" aria-label={`Pilih ${d.original_name}`} checked={selected.has(d.id)} onChange={() => toggle(d.id)} />
                  </td>
                  <td className="max-w-56 px-3 py-2">
                    <Link href={`/dokumen/${d.id}`} className="block truncate font-medium text-ink hover:underline">
                      {d.original_name}
                    </Link>
                    {d.error && <span className="block truncate text-xs text-bad">{d.error}</span>}
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={d.status} /></td>
                  <td className="px-3 py-2 text-ink-2">{d.doc_type ? DOC_TYPE_LABELS[d.doc_type] : '—'}</td>
                  <td className="max-w-48 truncate px-3 py-2 text-ink">{d.vendor_name ?? '—'}</td>
                  <td className="num px-3 py-2 text-ink-2">{formatDate(d.issue_date)}</td>
                  <td className="num px-3 py-2 text-right text-ink">{formatRupiah(d.total)}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-ink-2">{ENGINE_LABELS[d.engine]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} danger title={`Hapus ${selected.size} dokumen?`}
        description="Berkas asli, gambar halaman, hasil OCR, ekstraksi dan riwayat tinjauan ikut terhapus. Tindakan ini tidak dapat dibatalkan."
        confirmLabel="Hapus permanen" onConfirm={() => void removeSelected()} />
    </div>
  )
}

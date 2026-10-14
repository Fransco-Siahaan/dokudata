import { useEffect, useMemo, useState } from 'react'
import { absolute, api, useApi } from '../api/client'
import type { ArchiveResponse, DocumentList, ExportResponse } from '../api/types'
import { PageHeader } from '../components/Layout'
import { Button, Card, EmptyState, Segmented, StatusBadge, TextInput, notify } from '../components/ui'
import { formatDate, formatRupiah } from '../lib/format'
import { useLocation } from '../lib/router'

const READY = ['auto_approved', 'reviewed', 'exported']

/** Indented folder tree from flat archive paths. */
function Tree({ paths }: { paths: string[] }) {
  const lines = useMemo(() => {
    const seen = new Set<string>()
    const out: { depth: number; name: string; file: boolean }[] = []
    for (const p of [...paths].sort()) {
      const parts = p.split('/')
      parts.forEach((part, i) => {
        const key = parts.slice(0, i + 1).join('/')
        if (seen.has(key)) return
        seen.add(key)
        out.push({ depth: i, name: part, file: i === parts.length - 1 })
      })
    }
    return out
  }, [paths])
  return (
    <ul className="max-h-80 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-xs" aria-label="Pratinjau struktur folder">
      {lines.map((l, i) => (
        <li key={i} style={{ paddingLeft: `${l.depth * 1.1}rem` }} className={l.file ? 'text-ink' : 'font-semibold text-ink-2'}>
          <span aria-hidden className="text-muted">{l.file ? '· ' : '▸ '}</span>
          {l.name}
        </li>
      ))}
    </ul>
  )
}

export function ExportPage() {
  const { search } = useLocation()
  const preselected = search.get('ids')?.split(',').filter(Boolean)
  const [includeUnreviewed, setIncludeUnreviewed] = useState(false)
  const list = useApi<DocumentList>('/documents?limit=500')
  const docs = (list.data?.items ?? []).filter((d) => READY.includes(d.status) || (includeUnreviewed && d.status === 'needs_review'))
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [format, setFormat] = useState<'xlsx' | 'csv' | 'json'>('xlsx')
  const [namePattern, setNamePattern] = useState('{tanggal}_{vendor}_{nomor}_{total}')
  const [folderPattern, setFolderPattern] = useState('Arsip/{tahun}/{bulan}/{jenis}')
  const [preview, setPreview] = useState<ArchiveResponse | null>(null)
  const [result, setResult] = useState<ExportResponse | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    if (!list.data) return
    const ready = list.data.items.filter((d) => READY.includes(d.status)).map((d) => d.id)
    setSelected(new Set(preselected?.length ? preselected : ready))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.data])

  const ids = docs.filter((d) => selected.has(d.id)).map((d) => d.id)

  useEffect(() => {
    if (!ids.length) {
      setPreview(null)
      return
    }
    const t = setTimeout(async () => {
      try {
        setPreview(await api<ArchiveResponse>('/archive/organize', { method: 'POST', body: JSON.stringify({ document_ids: ids, name_pattern: namePattern, folder_pattern: folderPattern }) }))
      } catch (e) {
        setPreview(null)
        notify.error(e)
      }
    }, 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(','), namePattern, folderPattern])

  async function doExport() {
    setBusy('export')
    try {
      const res = await api<ExportResponse>('/exports', { method: 'POST', body: JSON.stringify({ document_ids: ids, format, include_unreviewed: includeUnreviewed }) })
      setResult(res)
      window.location.assign(absolute(res.download_url))
      void list.reload()
    } catch (e) {
      notify.error(e)
    } finally {
      setBusy(null)
    }
  }

  async function doArchive() {
    setBusy('archive')
    try {
      const res = await api<ArchiveResponse>('/archive/organize', { method: 'POST', body: JSON.stringify({ document_ids: ids, name_pattern: namePattern, folder_pattern: folderPattern, apply: true }) })
      if (res.zip_url) window.location.assign(absolute(res.zip_url))
      notify.success('Arsip ZIP dibuat', `${res.items.length} berkas dengan nama baru`)
    } catch (e) {
      notify.error(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <PageHeader title="Ekspor & arsip" description="Hanya dokumen yang lolos otomatis atau sudah ditinjau yang diekspor sebagai data tervalidasi." />
      {!list.loading && (list.data?.items.length ?? 0) === 0 ? (
        <EmptyState title="Belum ada dokumen untuk diekspor" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <Card title={`Pilih dokumen (${ids.length}/${docs.length})`} actions={
            <label className="flex items-center gap-2 text-xs text-ink-2">
              <input type="checkbox" checked={includeUnreviewed} onChange={(e) => setIncludeUnreviewed(e.target.checked)} />
              Sertakan yang belum ditinjau (ditandai di berkas)
            </label>
          }>
            <ul className="max-h-[60vh] divide-y divide-line overflow-auto">
              {docs.map((d) => (
                <li key={d.id}>
                  <label className="flex cursor-pointer items-center gap-3 py-2 text-sm">
                    <input type="checkbox" checked={selected.has(d.id)} onChange={() => setSelected((s) => {
                      const n = new Set(s)
                      if (n.has(d.id)) n.delete(d.id)
                      else n.add(d.id)
                      return n
                    })} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-ink">{d.vendor_name ?? d.original_name}</span>
                      <span className="text-xs text-ink-2">{formatDate(d.issue_date)} · {d.original_name}</span>
                    </span>
                    <span className="num text-ink">{formatRupiah(d.total)}</span>
                    <StatusBadge status={d.status} />
                  </label>
                </li>
              ))}
            </ul>
          </Card>
          <div className="space-y-4">
            <Card title="Ekspor data">
              <Segmented label="Format" value={format} onChange={(v) => setFormat(v as 'xlsx')} options={[
                { value: 'xlsx', label: 'Excel (.xlsx)' }, { value: 'csv', label: 'CSV' }, { value: 'json', label: 'JSON' },
              ]} />
              <p className="mt-2 text-xs text-ink-2">Excel berisi lembar <em>Ringkasan</em> (satu baris per dokumen) dan <em>Item</em> (satu baris per item).</p>
              <Button className="mt-3" onClick={() => void doExport()} disabled={!ids.length} loading={busy === 'export'}>Unduh {ids.length} dokumen</Button>
              {result && result.skipped.length > 0 && (
                <p className="mt-2 text-xs text-warn">{result.skipped.length} dilewati: {result.skipped.map((s) => `${s.name} (${s.reason})`).join(', ')}</p>
              )}
            </Card>
            <Card title="Penamaan & folder arsip">
              <div className="space-y-3">
                <label className="block text-xs font-medium text-ink-2">Pola nama berkas
                  <TextInput className="mt-1 font-mono" value={namePattern} onChange={(e) => setNamePattern(e.target.value)} />
                </label>
                <label className="block text-xs font-medium text-ink-2">Pola folder
                  <TextInput className="mt-1 font-mono" value={folderPattern} onChange={(e) => setFolderPattern(e.target.value)} />
                </label>
                <p className="text-xs text-ink-2">Tersedia: <code>{'{tanggal} {vendor} {nomor} {total} {tahun} {bulan} {jenis}'}</code></p>
                {preview && <Tree paths={preview.items.map((i) => i.path)} />}
                <Button variant="secondary" onClick={() => void doArchive()} disabled={!ids.length} loading={busy === 'archive'}>Unduh arsip ZIP</Button>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

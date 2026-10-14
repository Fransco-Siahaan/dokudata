import { FileUpload } from '@ark-ui/react/file-upload'
import { useState } from 'react'
import { api, useApi } from '../api/client'
import type { DocumentSummary, Engine, Health, UploadResponse } from '../api/types'
import { PageHeader } from '../components/Layout'
import { EngineChooser } from '../components/EngineChooser'
import { Button, Card, StatusBadge, notify } from '../components/ui'
import { ENGINE_LABELS, formatBytes } from '../lib/format'
import { Link } from '../lib/router'
import { useDocumentEvents } from '../lib/useDocumentEvents'

const MAX_MB = 10

function QueueRow({ doc }: { doc: DocumentSummary }) {
  const live = useDocumentEvents(doc.events_url, doc.status)
  const done = !['queued', 'preprocessing', 'ocr', 'classifying', 'extracting', 'validating'].includes(live.status)
  return (
    <li className="flex flex-wrap items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">{doc.original_name}</p>
        <p className="text-xs text-ink-2">
          {formatBytes(doc.size)} · {ENGINE_LABELS[doc.engine]}
          {live.error && <span className="text-bad"> · {live.error}</span>}
        </p>
      </div>
      <StatusBadge status={live.status} />
      {done && live.status !== 'failed' && (
        <Link href={`/dokumen/${doc.id}`} className="text-sm font-medium text-brand underline underline-offset-2">
          {live.status === 'needs_review' ? 'Tinjau' : 'Lihat'}
        </Link>
      )}
    </li>
  )
}

export function UploadPage() {
  const health = useApi<Health>('/health')
  const llm = health.data?.llm_configured ?? false
  const [engine, setEngine] = useState<Engine>('rules')
  const [queue, setQueue] = useState<DocumentSummary[]>([])
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([])
  const [uploading, setUploading] = useState(false)

  async function upload(files: File[]) {
    if (!files.length) return
    setUploading(true)
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    form.append('engine', engine)
    try {
      const res = await api<UploadResponse>('/documents', { method: 'POST', body: form })
      setQueue((q) => [...res.documents, ...q])
      setRejected((r) => [...res.rejected, ...r])
      if (res.documents.length) notify.success(`${res.documents.length} dokumen masuk antrean`)
    } catch (e) {
      notify.error(e)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Unggah dokumen"
        description="Foto nota, scan faktur, atau PDF. Maksimal 10 MB per berkas. Berkas dihapus otomatis setelah 24 jam dan tidak dipakai untuk melatih model."
      />
      <Card title="Metode ekstraksi" className="mb-5">
        <EngineChooser value={engine} onChange={setEngine} llmReady={llm} llmModel={health.data?.llm_model} />
      </Card>
      <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
        <div className="space-y-4">
          <FileUpload.Root
            maxFiles={20}
            maxFileSize={MAX_MB * 1024 * 1024}
            accept={['image/jpeg', 'image/png', 'application/pdf']}
            acceptedFiles={[]}
            onFileAccept={(d) => void upload(d.files)}
            onFileReject={(d) =>
              setRejected((r) => [
                ...d.files.map((f) => ({ name: f.file.name, reason: f.errors.includes('FILE_TOO_LARGE') ? `Lebih dari ${MAX_MB} MB` : 'Tipe berkas tidak didukung' })),
                ...r,
              ])
            }
          >
            <FileUpload.Label className="sr-only">Pilih berkas</FileUpload.Label>
            <FileUpload.Dropzone className="flex min-h-56 flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-line-strong bg-surface p-6 text-center transition data-dragging:border-brand data-dragging:bg-brand-soft">
              <svg aria-hidden viewBox="0 0 24 24" className="size-9 text-brand" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <p className="font-medium text-ink">Seret berkas ke sini</p>
              <p className="text-sm text-ink-2">JPG, PNG, atau PDF · bisa banyak sekaligus</p>
              <FileUpload.Trigger asChild>
                <Button variant="secondary" loading={uploading}>
                  Pilih berkas
                </Button>
              </FileUpload.Trigger>
            </FileUpload.Dropzone>
            <FileUpload.HiddenInput />
          </FileUpload.Root>
          {rejected.length > 0 && (
            <Card title="Ditolak">
              <ul className="space-y-1 text-sm">
                {rejected.map((r, i) => (
                  <li key={`${r.name}-${i}`} className="flex gap-2">
                    <span aria-hidden className="text-bad">✕</span>
                    <span className="font-medium text-ink">{r.name}</span>
                    <span className="text-ink-2">— {r.reason}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <Card title={`Antrean (${queue.length})`} actions={<Link href="/dokumen" className="text-sm text-brand underline underline-offset-2">Semua dokumen</Link>}>
          {queue.length === 0 ? (
            <p className="text-sm text-ink-2">Belum ada unggahan di halaman ini. Status setiap berkas diperbarui langsung.</p>
          ) : (
            <ul className="divide-y divide-line" aria-live="polite">
              {queue.map((d) => (
                <QueueRow key={d.id} doc={d} />
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

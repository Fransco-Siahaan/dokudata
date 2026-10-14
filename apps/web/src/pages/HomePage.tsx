import { useEffect, useState } from 'react'
import { absolute, api, useApi } from '../api/client'
import type { DocumentSummary, Engine, Health, Sample } from '../api/types'
import { AboutPanel } from '../components/About'
import { EngineChooser } from '../components/EngineChooser'
import { Button, Card, StatusBadge, notify } from '../components/ui'
import { DOC_TYPE_LABELS, formatPct } from '../lib/format'
import { Link, navigate } from '../lib/router'
import { isTerminal, useDocumentEvents } from '../lib/useDocumentEvents'

interface Headline {
  headline?: Record<string, number | null>
}

function Running({ doc }: { doc: DocumentSummary }) {
  const live = useDocumentEvents(doc.events_url, doc.status)
  useEffect(() => {
    if (isTerminal(live.status)) navigate(`/dokumen/${doc.id}`)
  }, [live.status, doc.id])
  return (
    <p className="mt-2 flex items-center gap-2 text-sm text-ink-2" role="status">
      <StatusBadge status={live.status} /> memproses {doc.original_name}…
    </p>
  )
}

export function HomePage() {
  const samples = useApi<Sample[]>('/demo/samples')
  const evalSummary = useApi<Headline>('/evaluation/summary')
  const health = useApi<Health>('/health')
  const llm = health.data?.llm_configured ?? false
  const [engine, setEngine] = useState<Engine>('rules')
  const [running, setRunning] = useState<DocumentSummary | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const h = evalSummary.data?.headline

  async function run(name: string) {
    setBusy(name)
    try {
      setRunning(await api<DocumentSummary>(`/demo/samples/${encodeURIComponent(name)}?engine=${engine}`, { method: 'POST' }))
    } catch (e) {
      notify.error(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-8">
      <section className="grid gap-6 lg:grid-cols-[1.3fr_1fr] lg:items-center">
        <div>
          <p className="text-sm font-medium text-brand">Dokumen administrasi → data terstruktur</p>
          <h1 className="mt-2 text-3xl font-semibold leading-tight text-ink sm:text-4xl">
            Foto nota dan faktur menjadi Excel yang sudah diperiksa.
          </h1>
          <p className="mt-3 max-w-xl text-ink-2">
            Baca dokumen, ambil datanya, cocokkan hitungannya, dan periksa hanya bagian yang meragukan.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button onClick={() => samples.data?.[0] && run(samples.data[0].name)} disabled={!samples.data?.length} loading={busy !== null}>
              Coba dengan dokumen contoh
            </Button>
            <Button variant="secondary" onClick={() => navigate('/unggah')}>
              Unggah dokumen sendiri
            </Button>
          </div>
          {running && <Running doc={running} />}
        </div>
        <Card title="Hasil evaluasi terbaru (data uji beku)">
          {h ? (
            <dl className="grid grid-cols-2 gap-4">
              {[
                ['F1 total', h.total_f1],
                ['F1 field utama', h.key_fields_f1],
                ['Klasifikasi (macro-F1)', h.classification_macro_f1],
                ['Lolos otomatis', h.automation_rate],
              ].map(([label, v]) => (
                <div key={label as string}>
                  <dt className="text-xs text-ink-2">{label}</dt>
                  <dd className="text-2xl font-semibold text-ink">{formatPct(v as number | null)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-ink-2">Belum ada laporan evaluasi di server ini.</p>
          )}
          <Link href="/evaluasi" className="mt-4 inline-block text-sm font-medium text-brand underline underline-offset-2">
            Lihat metode, metrik, dan analisis kesalahan
          </Link>
        </Card>
      </section>

      <AboutPanel />

      <section aria-labelledby="samples-title">
        <h2 id="samples-title" className="mb-1 text-base font-semibold text-ink">
          Dokumen contoh (sintetis)
        </h2>
        <p className="mb-3 text-sm text-ink-2">Pilih metode ekstraksi, lalu proses salah satu contoh dan bandingkan hasilnya di halaman Tinjauan.</p>
        <div className="mb-4">
          <EngineChooser compact value={engine} onChange={setEngine} llmReady={llm} llmModel={health.data?.llm_model} />
        </div>
        {samples.error && <p className="text-sm text-bad">Gagal memuat contoh: {samples.error.message}</p>}
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {samples.data?.map((s) => (
            <li key={s.name}>
              <Card className="h-full">
                <img src={absolute(s.thumbnail_url)} alt={`Pratinjau ${s.title}`} className="h-44 w-full rounded-md bg-surface-2 object-cover object-top ring-1 ring-line" loading="lazy" />
                <p className="mt-3 text-sm font-semibold text-ink">{s.title}</p>
                <p className="text-xs text-ink-2">
                  {DOC_TYPE_LABELS[s.doc_type] ?? s.doc_type} · {s.description}
                </p>
                <Button size="sm" variant="secondary" className="mt-3 w-full" onClick={() => run(s.name)} loading={busy === s.name} disabled={busy !== null}>
                  Proses contoh ini
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

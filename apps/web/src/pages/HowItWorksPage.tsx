import { AboutPanel } from '../components/About'
import { PageHeader } from '../components/Layout'
import { ENGINES } from '../lib/engines'
import { Card } from '../components/ui'

const STAGES = [
  { name: 'Terima', detail: 'Tipe berkas dicek dari isinya (magic bytes), ukuran ≤ 10 MB, PDF ≤ 10 halaman. Berkas disimpan, job masuk antrean.' },
  { name: 'Pra-proses', detail: 'Orientasi EXIF, koreksi perspektif foto, deskew, kurangi derau, CLAHE. PDF digital memakai lapisan teksnya langsung.' },
  { name: 'OCR', detail: 'PaddleOCR (PP-OCR via ONNX Runtime, CPU) membaca kata beserta posisi dan keyakinannya.' },
  { name: 'Klasifikasi', detail: 'TF-IDF + regresi logistik: nota, faktur, atau lainnya. Kelas "lainnya" membuat sistem berani menolak.' },
  { name: 'Ekstraksi', detail: 'A: aturan + tata letak. B: teks OCR ke Claude dengan skema JSON ketat. C: gambar ke Claude visi.' },
  { name: 'Validasi', detail: 'Σ item = subtotal, subtotal − diskon + pajak = total, qty × harga, tanggal, NPWP, tarif PPN dari konfigurasi.' },
  { name: 'Keyakinan', detail: 'Model kecil memprediksi "apakah field ini benar" dari sinyal OCR, validasi, dan kesepakatan antar metode; lalu dikalibrasi.' },
  { name: 'Tinjauan', detail: 'Hanya dokumen yang lolos semua gerbang yang otomatis; sisanya ditinjau dengan field bermasalah disorot.' },
  { name: 'Ekspor & arsip', detail: 'Excel/CSV/JSON dan ZIP dengan nama berpola, mis. 2026-03-14_TokoMajuJaya_NT-0231_1250000.pdf.' },
]

const DECISIONS = [
  ['Semua mesin di balik antarmuka yang sama', 'OCREngine, Classifier, dan Extractor punya kontrak yang sama, sehingga perbandingan metode hanya mengganti konfigurasi.'],
  ['Data sintetis yang dibuat sendiri', 'Tidak ada dokumen milik orang lain. Generator HTML → PDF → gambar memberi label kebenaran otomatis, plus augmentasi foto, scan, dan struk pudar.'],
  ['Himpunan uji dibekukan sejak awal', 'Hash SHA-256 setiap berkas uji dicatat sebelum model apa pun dilatih dan diverifikasi di setiap evaluasi. Ambang dipilih hanya dari data validasi.'],
  ['Keputusan otomatis dibuat oleh kode, bukan LLM', 'LLM hanya mengisi skema JSON; lolos atau tidaknya ditentukan aturan validasi dan keyakinan terkalibrasi. Teks dokumen tidak bisa "menyetujui" dirinya sendiri.'],
  ['Pertahanan prompt injection berlapis', 'Isi dokumen diperlakukan sebagai data, LLM tidak diberi alat, keluaran dibatasi skema, nilai harus muncul di teks OCR, dan dokumen berisi instruksi mencurigakan selalu ditinjau manusia.'],
  ['Aturan sebagai cadangan yang selalu ada', 'Jika LLM gagal atau tidak dikonfigurasi, mesin aturan lokal tetap berjalan dan dokumen dikirim ke tinjauan.'],
]

export function HowItWorksPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Cara kerja" description="Alur dari unggahan sampai Excel, dan alasan di balik keputusan desain utamanya." />
      <AboutPanel />
      <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Tahapan pipeline">
        {STAGES.map((s, i) => (
          <li key={s.name} className="relative rounded-xl bg-surface p-4 ring-1 ring-line">
            <span className="num absolute right-3 top-3 text-xs text-muted">{String(i + 1).padStart(2, '0')}</span>
            <p className="text-sm font-semibold text-ink">{s.name}</p>
            <p className="mt-1 text-sm text-ink-2">{s.detail}</p>
          </li>
        ))}
      </ol>
      <Card title="Tiga metode ekstraksi">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs text-ink-2">
              <tr><th className="py-1.5 font-medium">Metode</th><th className="font-medium">Cara kerja</th><th className="font-medium">Kelebihan</th><th className="font-medium">Kekurangan</th><th className="font-medium">Data</th></tr>
            </thead>
            <tbody className="divide-y divide-line align-top">
              {ENGINES.map((e) => (
                <tr key={e.id}>
                  <td className="py-2 pr-3 font-semibold text-ink">{e.code} · {e.name}</td>
                  <td className="py-2 pr-3 text-ink-2">{e.how}</td>
                  <td className="py-2 pr-3 text-ink-2">{e.strengths}</td>
                  <td className="py-2 pr-3 text-ink-2">{e.tradeoff}</td>
                  <td className="py-2 text-ink-2">{e.privacy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-ink-2">Apa pun metodenya, hasilnya melewati validasi yang sama, dan keputusan lolos otomatis dibuat oleh kode, bukan oleh LLM. Metode B dan C selalu dicek silang dengan metode A.</p>
      </Card>
      <Card title="Keputusan desain">
        <dl className="grid gap-4 md:grid-cols-2">
          {DECISIONS.map(([t, d]) => (
            <div key={t}>
              <dt className="text-sm font-semibold text-ink">{t}</dt>
              <dd className="mt-1 text-sm text-ink-2">{d}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  )
}

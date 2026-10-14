import { resetSession } from '../api/client'
import { PageHeader } from '../components/Layout'
import { Button, Card, notify } from '../components/ui'

export function PrivacyPage() {
  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader title="Privasi & data" />
      <Card>
        <ul className="list-disc space-y-2 pl-5 text-sm text-ink-2">
          <li>Demo ini tidak memakai akun. Peramban Anda membuat token sesi acak; hanya Anda yang dapat melihat dokumen yang Anda unggah.</li>
          <li>Berkas unggahan dan semua hasilnya <strong className="text-ink">dihapus otomatis setelah 24 jam</strong>. Anda juga bisa menghapusnya kapan saja dari halaman Dokumen.</li>
          <li>Unggahan pengunjung <strong className="text-ink">tidak dipakai untuk melatih model</strong>. Model dilatih hanya dengan dokumen sintetis.</li>
          <li>Mesin A (OCR + aturan) berjalan sepenuhnya di server ini. Mesin B dan C mengirim isi dokumen ke penyedia LLM (Claude API) untuk diproses.</li>
          <li>Jangan unggah dokumen rahasia, data medis, atau data pribadi orang lain ke demo publik.</li>
        </ul>
      </Card>
      <Button variant="secondary" onClick={() => { resetSession(); notify.success('Sesi baru dibuat', 'Dokumen sesi lama tidak lagi terlihat dan akan terhapus otomatis.'); window.location.assign('/') }}>
        Mulai sesi baru
      </Button>
    </div>
  )
}

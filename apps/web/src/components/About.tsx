import { cn } from '../lib/format'

/** What DokuData does and why it exists, in a few lines (shown on Demo and How it works). */
export function AboutPanel({ className }: { className?: string }) {
  return (
    <section aria-labelledby="about-title" className={cn('grid gap-4 rounded-xl bg-surface p-5 ring-1 ring-line md:grid-cols-2', className)}>
      <h2 id="about-title" className="sr-only">Tentang DokuData</h2>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-brand">Fungsi</p>
        <p className="mt-1 text-sm text-ink">
          Mengubah foto nota, scan faktur, dan PDF menjadi data terstruktur: vendor, tanggal, NPWP, pajak, total, dan item baris.
          Hitungannya dicek otomatis, bagian yang meragukan disorot untuk diperiksa, lalu hasilnya diekspor ke Excel/CSV/JSON
          dan berkasnya diarsipkan dengan nama yang rapi.
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-brand">Tujuan</p>
        <p className="mt-1 text-sm text-ink">
          Menghapus pekerjaan mengetik ulang dokumen ke Excel bagi staf administrasi, akuntan, dan pemilik usaha kecil, tanpa
          mengorbankan ketelitian: data bernilai uang hanya dianggap valid setelah lolos pemeriksaan atau ditinjau manusia.
          Sebagai proyek portofolio, setiap klaim kualitasnya diukur pada data uji yang dibekukan.
        </p>
      </div>
    </section>
  )
}

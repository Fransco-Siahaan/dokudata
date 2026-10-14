import type { Engine } from '../api/types'

export interface EngineInfo {
  id: Engine
  code: 'A' | 'B' | 'C'
  name: string
  how: string
  strengths: string
  tradeoff: string
  privacy: string
  needsLlm: boolean
}

export const ENGINES: EngineInfo[] = [
  {
    id: 'rules',
    code: 'A',
    name: 'OCR + aturan',
    how: 'OCR membaca teks dan posisinya, lalu aturan dan tata letak menentukan vendor, tanggal, total, dan item.',
    strengths: 'Cepat, gratis, mudah dijelaskan.',
    tradeoff: 'Rapuh pada tata letak yang belum pernah dilihat.',
    privacy: 'Berjalan sepenuhnya di server ini.',
    needsLlm: false,
  },
  {
    id: 'llm_ocr',
    code: 'B',
    name: 'OCR + LLM',
    how: 'Teks OCR beserta posisinya dikirim ke Claude, yang mengisi skema JSON ketat; hasilnya dicek silang dengan metode A.',
    strengths: 'Lebih tahan terhadap format baru; nilai tetap harus muncul di teks OCR.',
    tradeoff: 'Berbayar per dokumen dan lebih lambat.',
    privacy: 'Teks dokumen dikirim ke Claude API.',
    needsLlm: true,
  },
  {
    id: 'llm_vision',
    code: 'C',
    name: 'LLM visi',
    how: 'Gambar halaman langsung dibaca Claude tanpa bergantung pada OCR; OCR tetap dipakai untuk menyorot lokasi dan memeriksa nilai.',
    strengths: 'Membaca tata letak dan teks kecil yang sulit bagi OCR.',
    tradeoff: 'Berbayar per dokumen; posisi field tidak sepresisi OCR.',
    privacy: 'Gambar dokumen dikirim ke Claude API.',
    needsLlm: true,
  },
]

export const engineInfo = (id: string) => ENGINES.find((e) => e.id === id)

export const LLM_SETUP_HINT =
  'Untuk mengaktifkan B dan C, isi ANTHROPIC_API_KEY di berkas .env proyek (atau jalankan `ant auth login`), lalu mulai ulang API.'

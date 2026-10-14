export const cn = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(' ')

const rupiah = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 2 })
const number = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 })
const pct = new Intl.NumberFormat('id-ID', { style: 'percent', maximumFractionDigits: 1 })

export const formatRupiah = (v: number | null | undefined) => (v == null ? '—' : rupiah.format(v))
export const formatNumber = (v: number | null | undefined) => (v == null ? '—' : number.format(v))
export const formatPct = (v: number | null | undefined) => (v == null ? '—' : pct.format(v))
export const formatDate = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' })
}
export const formatBytes = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`)

/** Parse what a reviewer types: "1.250.000", "Rp 1.250.000,50", "1250000". */
export function parseAmountInput(raw: string): number | null {
  const s = raw.replace(/rp|idr|\s/gi, '').replace(/,-$/, '')
  if (!s) return null
  let norm = s
  if (s.includes('.') && s.includes(',')) norm = s.lastIndexOf(',') > s.lastIndexOf('.') ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '')
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) norm = s.replace(/\./g, '')
  else if (/^\d{1,3}(,\d{3})+$/.test(s)) norm = s.replace(/,/g, '')
  else norm = s.replace(',', '.')
  const v = Number(norm)
  return Number.isFinite(v) ? v : null
}

export const FIELD_LABELS: Record<string, string> = {
  vendor_name: 'Vendor',
  vendor_tax_id: 'NPWP vendor',
  document_number: 'Nomor dokumen',
  issue_date: 'Tanggal',
  due_date: 'Jatuh tempo',
  currency: 'Mata uang',
  subtotal: 'Subtotal',
  discount: 'Diskon',
  tax_amount: 'Pajak (PPN)',
  total: 'Total',
  payment_method: 'Metode bayar',
  line_items: 'Item baris',
}

export const DOC_TYPE_LABELS: Record<string, string> = { receipt: 'Nota', invoice: 'Faktur', other: 'Lainnya' }
export const ENGINE_LABELS: Record<string, string> = {
  rules: 'A · OCR + aturan',
  llm_ocr: 'B · OCR + LLM',
  llm_vision: 'C · LLM visi',
}
export const PAYMENT_LABELS: Record<string, string> = {
  cash: 'Tunai',
  debit_card: 'Kartu debit',
  credit_card: 'Kartu kredit',
  qris: 'QRIS',
  bank_transfer: 'Transfer bank',
  e_wallet: 'Dompet digital',
}

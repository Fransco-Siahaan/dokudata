export type DocStatus =
  | 'queued' | 'preprocessing' | 'ocr' | 'classifying' | 'extracting' | 'validating'
  | 'auto_approved' | 'needs_review' | 'rejected' | 'reviewed' | 'exported' | 'failed'

export type Engine = 'rules' | 'llm_ocr' | 'llm_vision'

export interface DocumentSummary {
  id: string
  original_name: string
  mime: string
  size: number
  status: DocStatus
  doc_type: string | null
  decision: string | null
  engine: Engine
  vendor_name: string | null
  issue_date: string | null
  total: number | null
  error: string | null
  is_sample: boolean
  archive_path: string | null
  created_at: string
  events_url: string
  thumbnail_url: string | null
}

export interface FieldValue {
  value: string | number | null
  confidence: number | null
  source: string | null
  bbox: number[] | null
  page: number | null
  raw: string | null
}

export interface LineItem {
  description: string | null
  qty: number | null
  unit_price: number | null
  amount: number | null
  confidence?: number | null
  bbox?: number[] | null
  page?: number | null
}

export type Extraction = Record<string, FieldValue> & { line_items: LineItem[] }

export interface Finding {
  rule: string
  status: 'pass' | 'warning' | 'fail' | 'skipped'
  fields: string[]
  detail: string
}

export interface DocumentResult {
  document_type: FieldValue
  extraction: Extraction
  validation: Finding[]
  decision: 'auto_approved' | 'needs_review' | 'rejected'
  decision_reasons: string[]
  document_confidence: number
  engines: Record<string, string>
  timings_ms: Record<string, number>
  cost_usd: number
  flags: string[]
  thresholds?: { field?: number; classifier?: number }
}

export interface Values {
  line_items: LineItem[]
  [k: string]: string | number | null | LineItem[]
}

export interface DocumentDetail extends DocumentSummary {
  result: DocumentResult | null
  final_data: Values | null
  data: Values | null
  pages: { number: number; url: string; width: number; height: number; preprocess: string[] }[]
  original_url: string
  reviews: number
}

export interface DocumentList {
  items: DocumentSummary[]
  total: number
  counts: Record<string, number>
}

export interface UploadResponse {
  documents: DocumentSummary[]
  rejected: { name: string; reason: string }[]
}

export interface Sample {
  name: string
  title: string
  doc_type: string
  description: string
  thumbnail_url: string
}

export interface ExportResponse {
  id: string
  filename: string
  format: string
  count: number
  skipped: { name: string; reason: string }[]
  download_url: string
}

export interface ArchiveResponse {
  items: { document_id: string; original_name: string; path: string }[]
  zip_url: string | null
}

export interface Health {
  status: 'ok' | 'degraded'
  llm_configured: boolean
  llm_model: string | null
  models: Record<string, boolean>
  queue_mode: string
}

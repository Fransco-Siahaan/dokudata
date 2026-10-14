// Base UI: Ark UI (accessible, headless) + Tailwind tokens.
import { createListCollection } from '@ark-ui/react/collection'
import { Dialog } from '@ark-ui/react/dialog'
import { Portal } from '@ark-ui/react/portal'
import { SegmentGroup } from '@ark-ui/react/segment-group'
import { Select } from '@ark-ui/react/select'
import { createToaster, Toast, Toaster } from '@ark-ui/react/toast'
import { forwardRef, useMemo, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from 'react'
import type { DocStatus } from '../api/types'
import { cn, formatPct } from '../lib/format'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-brand-ink hover:opacity-90',
  secondary: 'bg-surface text-ink ring-1 ring-line-strong hover:bg-surface-2',
  ghost: 'text-ink-2 hover:bg-surface-2',
  danger: 'bg-bad text-white hover:opacity-90',
  success: 'bg-good text-white hover:opacity-90',
}

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; loading?: boolean }
>(function Button({ variant = 'primary', size = 'md', loading, className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3 text-sm' : 'h-10 px-4 text-sm',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading && <span className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  )
})

export function Card({ className, children, title, actions }: { className?: string; children: ReactNode; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={cn('rounded-xl bg-surface ring-1 ring-line', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export const inputClass =
  'h-10 w-full rounded-lg bg-surface px-3 text-sm text-ink ring-1 ring-line-strong placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand aria-[invalid=true]:ring-bad'

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function TextInput(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn(inputClass, className)} {...rest} />
})

// ---------- Status and confidence: icon + text, never color alone (PRD 14.2) ----------

const STATUS: Record<DocStatus, { label: string; icon: string; tone: string }> = {
  queued: { label: 'Antre', icon: '◷', tone: 'bg-surface-2 text-ink-2' },
  preprocessing: { label: 'Pra-proses', icon: '◔', tone: 'bg-brand-soft text-brand' },
  ocr: { label: 'OCR', icon: '◑', tone: 'bg-brand-soft text-brand' },
  classifying: { label: 'Klasifikasi', icon: '◕', tone: 'bg-brand-soft text-brand' },
  extracting: { label: 'Ekstraksi', icon: '◕', tone: 'bg-brand-soft text-brand' },
  validating: { label: 'Validasi', icon: '◕', tone: 'bg-brand-soft text-brand' },
  auto_approved: { label: 'Lolos otomatis', icon: '✓', tone: 'bg-good-soft text-good' },
  needs_review: { label: 'Perlu tinjau', icon: '!', tone: 'bg-warn-soft text-warn' },
  rejected: { label: 'Di luar cakupan', icon: '⊘', tone: 'bg-surface-2 text-ink-2' },
  reviewed: { label: 'Ditinjau', icon: '✓', tone: 'bg-good-soft text-good' },
  exported: { label: 'Diekspor', icon: '⇩', tone: 'bg-surface-2 text-ink-2' },
  failed: { label: 'Gagal', icon: '✕', tone: 'bg-bad-soft text-bad' },
}

export const PROCESSING: DocStatus[] = ['queued', 'preprocessing', 'ocr', 'classifying', 'extracting', 'validating']

export function StatusBadge({ status }: { status: DocStatus }) {
  const s = STATUS[status] ?? STATUS.queued
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium', s.tone)}>
      <span aria-hidden className={cn(PROCESSING.includes(status) && 'animate-pulse')}>
        {s.icon}
      </span>
      {s.label}
    </span>
  )
}

export function statusLabel(status: DocStatus) {
  return STATUS[status]?.label ?? status
}

export function ConfidenceBadge({ value, threshold = 0.9 }: { value: number | null | undefined; threshold?: number }) {
  if (value == null) return <span className="text-xs text-muted">—</span>
  const level = value >= threshold ? 'high' : value >= 0.6 ? 'mid' : 'low'
  const map = {
    high: { icon: '●', label: 'yakin', tone: 'text-good' },
    mid: { icon: '◐', label: 'periksa', tone: 'text-warn' },
    low: { icon: '○', label: 'ragu', tone: 'text-bad' },
  }[level]
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium', map.tone)} title={`Keyakinan ${formatPct(value)}`}>
      <span aria-hidden>{map.icon}</span>
      <span className="num">{formatPct(value)}</span>
      <span className="sr-only sm:not-sr-only">· {map.label}</span>
    </span>
  )
}

// ---------- Select & segmented control ----------

export interface Option {
  value: string
  label: string
  disabled?: boolean
}

export function SelectField({ label, value, options, onChange, placeholder, className }: {
  label?: string
  value: string
  options: Option[]
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}) {
  const collection = useMemo(() => createListCollection({ items: options }), [options])
  return (
    <Select.Root collection={collection} value={value ? [value] : []} onValueChange={(d) => onChange(d.value[0] ?? '')} positioning={{ sameWidth: true }} className={cn('flex flex-col gap-1', className)}>
      {label && <Select.Label className="text-xs font-medium text-ink-2">{label}</Select.Label>}
      <Select.Control>
        <Select.Trigger className={cn(inputClass, 'flex items-center justify-between gap-2 text-left')}>
          <Select.ValueText placeholder={placeholder} className="truncate" />
          <Select.Indicator className="text-muted">▾</Select.Indicator>
        </Select.Trigger>
      </Select.Control>
      <Portal>
        <Select.Positioner>
          <Select.Content className="z-50 max-h-72 overflow-auto rounded-lg bg-surface p-1 shadow-lg ring-1 ring-line-strong focus:outline-none">
            {collection.items.map((item) => (
              <Select.Item key={item.value} item={item} className="flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm text-ink data-highlighted:bg-surface-2 data-[state=checked]:font-semibold data-disabled:cursor-not-allowed data-disabled:opacity-50">
                <Select.ItemText>{item.label}</Select.ItemText>
                <Select.ItemIndicator className="text-brand">✓</Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Content>
        </Select.Positioner>
      </Portal>
      <Select.HiddenSelect />
    </Select.Root>
  )
}

export function Segmented({ label, value, options, onChange }: { label: string; value: string; options: Option[]; onChange: (v: string) => void }) {
  return (
    <SegmentGroup.Root value={value} onValueChange={(d) => d.value && onChange(d.value)} className="relative inline-flex flex-wrap rounded-lg bg-surface-2 p-1" aria-label={label}>
      <SegmentGroup.Indicator className="rounded-md bg-surface shadow-sm ring-1 ring-line" style={{ width: 'var(--width)', height: 'var(--height)', left: 'var(--left)', top: 'var(--top)', position: 'absolute', transition: 'all .15s' }} />
      {options.map((o) => (
        <SegmentGroup.Item key={o.value} value={o.value} className="relative z-10 cursor-pointer rounded-md px-3 py-1.5 text-sm text-ink-2 data-[state=checked]:font-semibold data-[state=checked]:text-ink">
          <SegmentGroup.ItemText>{o.label}</SegmentGroup.ItemText>
          <SegmentGroup.ItemControl />
          <SegmentGroup.ItemHiddenInput />
        </SegmentGroup.Item>
      ))}
    </SegmentGroup.Root>
  )
}

// ---------- Dialog ----------

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, onConfirm, danger }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  confirmLabel: string
  onConfirm: () => void
  danger?: boolean
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(d) => onOpenChange(d.open)} lazyMount unmountOnExit role="alertdialog">
      <Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Positioner className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <Dialog.Content className="w-full max-w-md rounded-xl bg-surface p-5 shadow-xl ring-1 ring-line">
            <Dialog.Title className="text-base font-semibold text-ink">{title}</Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-ink-2">{description}</Dialog.Description>
            <div className="mt-5 flex justify-end gap-2">
              <Dialog.CloseTrigger asChild>
                <Button variant="secondary">Batal</Button>
              </Dialog.CloseTrigger>
              <Button variant={danger ? 'danger' : 'primary'} onClick={() => { onConfirm(); onOpenChange(false) }}>
                {confirmLabel}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  )
}

// ---------- Toasts ----------

export const toaster = createToaster({ placement: 'bottom-end', gap: 8, max: 4 })

export const notify = {
  success: (title: string, description?: string) => toaster.create({ title, description, type: 'success', duration: 3500 }),
  info: (title: string, description?: string) => toaster.create({ title, description, type: 'info', duration: 3500 }),
  error: (e: unknown, fallback = 'Terjadi kesalahan') =>
    toaster.create({ title: e instanceof Error ? e.message : fallback, type: 'error', duration: 6000 }),
}

export function AppToaster() {
  return (
    <Toaster toaster={toaster}>
      {(t) => (
        <Toast.Root className="flex w-[min(92vw,380px)] items-start gap-3 rounded-lg bg-surface p-3 shadow-lg ring-1 ring-line-strong data-[type=error]:ring-bad data-[type=success]:ring-good">
          <span aria-hidden className={cn('mt-0.5 text-sm', t.type === 'error' ? 'text-bad' : t.type === 'success' ? 'text-good' : 'text-brand')}>
            {t.type === 'error' ? '✕' : t.type === 'success' ? '✓' : 'ℹ'}
          </span>
          <div className="min-w-0 flex-1">
            <Toast.Title className="text-sm font-semibold text-ink">{t.title}</Toast.Title>
            {t.description && <Toast.Description className="text-sm text-ink-2">{t.description}</Toast.Description>}
          </div>
          <Toast.CloseTrigger aria-label="Tutup" className="text-muted hover:text-ink">×</Toast.CloseTrigger>
        </Toast.Root>
      )}
    </Toaster>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong p-8 text-center">
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="mt-2 text-sm text-ink-2">{children}</div>}
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2">{children}</kbd>
}

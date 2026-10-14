import { useId } from 'react'
import type { Engine } from '../api/types'
import { ENGINES, LLM_SETUP_HINT } from '../lib/engines'
import { cn } from '../lib/format'

/** Pick extraction method A, B or C. B and C stay visible but disabled until Claude is configured. */
export function EngineChooser({ value, onChange, llmReady, llmModel, compact }: {
  value: Engine
  onChange: (e: Engine) => void
  llmReady: boolean
  llmModel?: string | null
  compact?: boolean
}) {
  const name = useId()
  return (
    <fieldset>
      <legend className="sr-only">Metode ekstraksi</legend>
      <div className={cn('grid gap-2', compact ? 'sm:grid-cols-3' : 'md:grid-cols-3')}>
        {ENGINES.map((e) => {
          const disabled = e.needsLlm && !llmReady
          const checked = value === e.id
          return (
            <label
              key={e.id}
              className={cn(
                'relative flex cursor-pointer flex-col gap-1 rounded-lg p-3 ring-1 transition',
                checked ? 'bg-brand-soft ring-2 ring-brand' : 'bg-surface ring-line hover:bg-surface-2',
                disabled && 'cursor-not-allowed opacity-60 hover:bg-surface',
              )}
            >
              <input type="radio" name={name} value={e.id} checked={checked} disabled={disabled}
                onChange={() => onChange(e.id)} className="sr-only" />
              <span className="flex items-center gap-2">
                <span aria-hidden className={cn('grid size-6 place-items-center rounded-md text-xs font-bold',
                  checked ? 'bg-brand text-brand-ink' : 'bg-surface-2 text-ink-2')}>{e.code}</span>
                <span className="text-sm font-semibold text-ink">{e.name}</span>
                {disabled && <span className="ml-auto rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-ink-2">belum aktif</span>}
                {checked && !disabled && <span aria-hidden className="ml-auto text-brand">✓</span>}
              </span>
              {!compact && (
                <>
                  <span className="text-xs text-ink-2">{e.how}</span>
                  <span className="text-xs text-ink"><span className="text-good">+</span> {e.strengths}</span>
                  <span className="text-xs text-ink"><span className="text-warn">−</span> {e.tradeoff}</span>
                  <span className="text-xs text-muted">{e.privacy}{e.needsLlm && llmReady && llmModel ? ` · model ${llmModel}` : ''}</span>
                </>
              )}
            </label>
          )
        })}
      </div>
      {!llmReady && <p className="mt-2 text-xs text-ink-2">{LLM_SETUP_HINT}</p>}
    </fieldset>
  )
}

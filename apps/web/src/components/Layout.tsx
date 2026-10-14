import { useEffect, useState, type ReactNode } from 'react'
import { cn } from '../lib/format'
import { Link, useLocation } from '../lib/router'

const NAV = [
  { href: '/', label: 'Demo' },
  { href: '/unggah', label: 'Unggah' },
  { href: '/dokumen', label: 'Dokumen' },
  { href: '/ekspor', label: 'Ekspor & Arsip' },
  { href: '/evaluasi', label: 'Evaluasi' },
  { href: '/cara-kerja', label: 'Cara Kerja' },
]

type Theme = 'system' | 'light' | 'dark'

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem('dokudata.theme') as Theme) || 'system'
    } catch {
      return 'system'
    }
  })
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try {
      localStorage.setItem('dokudata.theme', theme)
    } catch {
      /* ignore */
    }
  }, [theme])
  return [theme, setTheme]
}

export function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const [theme, setTheme] = useTheme()
  const next: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' }
  const themeLabel = { system: 'Tema: sistem', light: 'Tema: terang', dark: 'Tema: gelap' }[theme]
  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Lewati ke konten
      </a>
      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2.5">
          <Link href="/" className="flex shrink-0 items-center gap-2 font-semibold text-ink">
            <img src="/favicon.svg" alt="" className="size-7" />
            DokuData
          </Link>
          <nav aria-label="Navigasi utama" className="-mx-1 flex min-w-0 flex-1 gap-1 overflow-x-auto">
            {NAV.map((n) => {
              const active = n.href === '/' ? pathname === '/' : pathname.startsWith(n.href)
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  aria-current={active ? 'page' : undefined}
                  className={cn('whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm', active ? 'bg-brand-soft font-semibold text-brand' : 'text-ink-2 hover:bg-surface-2')}
                >
                  {n.label}
                </Link>
              )
            })}
          </nav>
          <button type="button" onClick={() => setTheme(next[theme])} className="shrink-0 rounded-md px-2 py-1.5 text-xs text-ink-2 ring-1 ring-line hover:bg-surface-2" aria-label={`${themeLabel}. Ganti tema`}>
            {theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐'}
          </button>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        {children}
      </main>
      <footer className="border-t border-line bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs text-ink-2">
          <span>DokuData · proyek portofolio AI dokumen → data. Semua contoh adalah dokumen sintetis.</span>
          <Link href="/privasi" className="underline underline-offset-2 hover:text-ink">
            Privasi &amp; data
          </Link>
        </div>
      </footer>
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions}
    </div>
  )
}

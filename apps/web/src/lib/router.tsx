// Minimal router on the History API (same approach as the Pintar Saku project).
import { useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from 'react'

const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())
if (typeof window !== 'undefined') window.addEventListener('popstate', emit)

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => void listeners.delete(l)
}
const snapshot = () => window.location.pathname + window.location.search

export function navigate(to: string, opts: { replace?: boolean } = {}) {
  if (to !== snapshot()) {
    window.history[opts.replace ? 'replaceState' : 'pushState']({}, '', to)
    emit()
  }
  window.scrollTo(0, 0)
}

export function useLocation() {
  const full = useSyncExternalStore(subscribe, snapshot, () => '/')
  const [pathname, search = ''] = full.split('?')
  return { pathname, search: new URLSearchParams(search) }
}

export function matchPath(pattern: string, pathname: string): Record<string, string> | null {
  const keys: string[] = []
  const re = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), '([^/]+)')) + '/?$')
  const m = pathname.match(re)
  return m ? Object.fromEntries(keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])) : null
}

export function Link({ href, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e)
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || href.startsWith('http')) return
    e.preventDefault()
    navigate(href)
  }
  return <a href={href} onClick={handle} {...rest} />
}

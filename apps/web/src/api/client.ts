// API client. Each browser gets a random anonymous session token, so a visitor
// only ever sees the documents they uploaded (no accounts in the demo).
import { useCallback, useEffect, useRef, useState } from 'react'

const SESSION_KEY = 'dokudata.session'
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

function newToken(): string {
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function sessionToken(): string {
  try {
    let t = localStorage.getItem(SESSION_KEY)
    if (!t) {
      t = newToken()
      localStorage.setItem(SESSION_KEY, t)
    }
    return t
  } catch {
    // Private mode without storage: keep one token for this tab's lifetime.
    const w = window as unknown as { __dokudataToken?: string }
    w.__dokudataToken ??= newToken()
    return w.__dokudataToken
  }
}

export function resetSession() {
  try {
    localStorage.removeItem(SESSION_KEY)
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

export const absolute = (url: string) => (url.startsWith('http') ? url : `${BASE}${url}`)

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-DokuData-Session', sessionToken())
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(`${BASE}/api/v1${path}`, { ...init, headers })
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = body?.detail
    const message =
      typeof detail === 'string' ? detail : (detail?.message as string | undefined) ?? `Permintaan gagal (${res.status})`
    throw new ApiError(res.status, message, detail)
  }
  return body as T
}

/** Fetch on mount and whenever `path` changes; keeps the previous data while refetching. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(Boolean(path))
  const seq = useRef(0)
  const load = useCallback(async () => {
    if (!path) return
    const id = ++seq.current
    setLoading(true)
    try {
      const d = await api<T>(path)
      if (id === seq.current) {
        setData(d)
        setError(null)
      }
    } catch (e) {
      if (id === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e), null))
    } finally {
      if (id === seq.current) setLoading(false)
    }
  }, [path])
  useEffect(() => {
    void load()
  }, [load])
  return { data, error, loading, reload: load, setData }
}

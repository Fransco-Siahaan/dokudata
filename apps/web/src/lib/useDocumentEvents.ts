import { useEffect, useState } from 'react'
import { absolute } from '../api/client'
import type { DocStatus } from '../api/types'

const TERMINAL: DocStatus[] = ['auto_approved', 'needs_review', 'rejected', 'reviewed', 'exported', 'failed']

export interface LiveStatus {
  status: DocStatus
  decision: string | null
  error: string | null
}

/** Follow a document's status over server-sent events (signed URL; no headers needed). */
export function useDocumentEvents(eventsUrl: string | null, initial: DocStatus): LiveStatus {
  const [state, setState] = useState<LiveStatus>({ status: initial, decision: null, error: null })
  useEffect(() => {
    if (!eventsUrl || TERMINAL.includes(initial)) return
    const es = new EventSource(absolute(eventsUrl))
    es.addEventListener('status', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as LiveStatus
      setState(data)
      if (TERMINAL.includes(data.status)) es.close()
    })
    es.onerror = () => es.close()
    return () => es.close()
  }, [eventsUrl, initial])
  return state
}

export const isTerminal = (s: DocStatus) => TERMINAL.includes(s)

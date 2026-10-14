import { useEffect, type ReactNode } from 'react'
import { AppToaster } from './components/ui'
import { Layout } from './components/Layout'
import { matchPath, useLocation } from './lib/router'
import { DocumentsPage } from './pages/DocumentsPage'
import { EvaluationPage } from './pages/EvaluationPage'
import { ExportPage } from './pages/ExportPage'
import { HomePage } from './pages/HomePage'
import { HowItWorksPage } from './pages/HowItWorksPage'
import { PrivacyPage } from './pages/PrivacyPage'
import { ReviewPage } from './pages/ReviewPage'
import { UploadPage } from './pages/UploadPage'

const ROUTES: { path: string; title: string; render: (p: Record<string, string>) => ReactNode }[] = [
  { path: '/', title: 'Demo', render: () => <HomePage /> },
  { path: '/unggah', title: 'Unggah', render: () => <UploadPage /> },
  { path: '/dokumen', title: 'Dokumen', render: () => <DocumentsPage /> },
  { path: '/dokumen/:id', title: 'Tinjauan', render: (p) => <ReviewPage key={p.id} id={p.id} /> },
  { path: '/ekspor', title: 'Ekspor & Arsip', render: () => <ExportPage /> },
  { path: '/evaluasi', title: 'Evaluasi', render: () => <EvaluationPage /> },
  { path: '/cara-kerja', title: 'Cara Kerja', render: () => <HowItWorksPage /> },
  { path: '/privasi', title: 'Privasi', render: () => <PrivacyPage /> },
]

export default function App() {
  const { pathname } = useLocation()
  let match: { title: string; node: ReactNode } | null = null
  for (const r of ROUTES) {
    const params = matchPath(r.path, pathname)
    if (params) {
      match = { title: r.title, node: r.render(params) }
      break
    }
  }
  const title = match?.title ?? 'Tidak ditemukan'
  useEffect(() => {
    document.title = `${title} · DokuData`
  }, [title])
  return (
    <Layout>
      {match?.node ?? <p className="text-ink-2">Halaman tidak ditemukan.</p>}
      <AppToaster />
    </Layout>
  )
}

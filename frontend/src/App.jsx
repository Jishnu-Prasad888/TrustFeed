import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Profiles  from './pages/Profiles'
import Posts     from './pages/Posts'
import RAGPage   from './pages/RAGPage'
import Settings  from './pages/Settings'

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 10_000 } } })

export default function App() {
  const [page, setPage] = useState('dashboard')

  const pages = { dashboard: Dashboard, profiles: Profiles, posts: Posts, rag: RAGPage, settings: Settings }
  const Page  = pages[page] || Dashboard

  return (
    <QueryClientProvider client={qc}>
      <div className="app-shell">
        <Sidebar current={page} navigate={setPage} />
        <main className="main-content">
          <Page navigate={setPage} />
        </main>
      </div>
      <Toaster position="bottom-right" toastOptions={{
        style: { background: '#0f1117', color: '#e2e8f0', border: '1px solid #2d3748' }
      }} />
    </QueryClientProvider>
  )
}

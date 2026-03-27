import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchStats, triggerScrape, fetchProfiles } from '../api'
import { RefreshCw, Database, Users, FileText, Zap, Clock } from 'lucide-react'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from 'date-fns'

function StatCard({ icon: Icon, label, value, accent }) {
  return (
    <div className="stat-card" style={{ '--accent': accent }}>
      <div className="stat-icon"><Icon size={20} /></div>
      <div className="stat-body">
        <div className="stat-value">{value ?? '—'}</div>
        <div className="stat-label">{label}</div>
      </div>
    </div>
  )
}

export default function Dashboard({ navigate }) {
  const qc = useQueryClient()
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: fetchStats, refetchInterval: 15_000 })
  const { data: profiles } = useQuery({ queryKey: ['profiles'], queryFn: fetchProfiles })

  const scrape = useMutation({
    mutationFn: triggerScrape,
    onSuccess: () => { toast.success('Scrape cycle started'); qc.invalidateQueries() },
    onError:   () => toast.error('Scrape failed'),
  })

  const activeProfiles = profiles?.filter(p => p.is_active) ?? []

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-sub">System overview and quick actions</p>
        </div>
        <button className="btn-primary" onClick={() => scrape.mutate()} disabled={scrape.isPending}>
          <RefreshCw size={16} className={scrape.isPending ? 'spin' : ''} />
          {scrape.isPending ? 'Scraping…' : 'Scrape Now'}
        </button>
      </div>

      <div className="stat-grid">
        <StatCard icon={Users}    label="Total Profiles"   value={stats?.total_profiles}  accent="#6366f1" />
        <StatCard icon={Zap}      label="Active Profiles"  value={stats?.active_profiles} accent="#22c55e" />
        <StatCard icon={FileText} label="Posts Scraped"    value={stats?.total_posts}     accent="#f59e0b" />
        <StatCard icon={Database} label="Vectors Stored"   value={stats?.vector_count}    accent="#0ea5e9" />
      </div>

      {stats?.next_scrape && (
        <div className="info-banner">
          <Clock size={15} />
          Next automatic scrape: <strong>{formatDistanceToNow(new Date(stats.next_scrape), { addSuffix: true })}</strong>
        </div>
      )}

      <div className="section-title">Active Profiles</div>
      {activeProfiles.length === 0 ? (
        <div className="empty-state">
          No active profiles yet.{' '}
          <button className="link-btn" onClick={() => navigate('profiles')}>Add one →</button>
        </div>
      ) : (
        <div className="profile-list-mini">
          {activeProfiles.map(p => (
            <div key={p.id} className="profile-mini-card">
              <div className="profile-mini-name">{p.name}</div>
              <div className="profile-mini-meta">
                <span className="badge badge-platform">{p.platform}</span>
                <span className="trust-pill" style={{ '--t': p.trust }}>
                  trust {(p.trust * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
